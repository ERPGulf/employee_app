# Regression tests for HR changes to an employee's Authentication and High Security.
#   bench --site <test-site> run-tests --module employee_app.tests.test_auth_policy_transitions

from unittest.mock import patch

import frappe

from employee_app import auth_audit, auth_core
from employee_app.authentication import get_employee_login_policy, get_login_policies, sign_up_api
from employee_app.gauth import create_new_password
from employee_app.sign_in import otp_generate_for_sign_in, sign_in_api
from employee_app.tests.test_auth_remediation import TEST_OTP, AuthTestCase, can_log_in, reply

test_dependencies = ["Employee"]

PASSWORD, OTP, OPTIONAL, BOTH = "Password Authentication", "OTP Authentication", "Optional", "Both"

# from, to, has an own password, sessions end, HR's first-password grant
TRANSITIONS = (
    (OTP, PASSWORD, True, True, False),
    (OTP, PASSWORD, False, True, True),
    (OTP, BOTH, False, True, True),
    (OTP, OPTIONAL, False, False, False),
    (PASSWORD, OTP, True, True, False),
    (PASSWORD, BOTH, True, True, False),
    (PASSWORD, BOTH, False, True, True),
    (PASSWORD, OPTIONAL, True, False, False),
    (BOTH, PASSWORD, True, False, False),
    (BOTH, OTP, True, False, False),
    (BOTH, OPTIONAL, True, False, False),
    (OPTIONAL, PASSWORD, True, True, False),
    (OPTIONAL, PASSWORD, False, True, True),
    (OPTIONAL, OTP, True, True, False),
)


class TransitionTestCase(AuthTestCase):
    def setUp(self):
        super().setUp()
        # The tenant switch stays off: nothing below may depend on it.
        frappe.db.set_single_value("Checkin App Setting", "allow_in_app_password_setup", 0)

    def employee(self, authentication, own_password, **kwargs):
        password = self.chosen_password if own_password else self.legacy_password
        emp = self.make(authentication, own_password=int(own_password), password=password, **kwargs)
        emp.password = password
        return emp

    def change(self, emp, **values):
        """An HR edit in Desk: a document save, so the Employee hooks run."""
        doc = frappe.get_doc("Employee", emp.name)
        doc.update(values)
        doc.save()

    def policy(self, emp):
        status, body = reply(get_employee_login_policy(mobile=emp.mobile))
        self.assertEqual(status, 200)
        return body

    def field(self, emp, fieldname):
        return frappe.db.get_value("Employee", emp.name, fieldname)

    def fresh_otp(self, emp):
        frappe.cache().delete_keys("employee_app:auth:")  # lifts the one-send-a-minute limit between steps
        return self.otp(emp)


class TestPolicyTransitions(TransitionTestCase):
    def test_transition_matrix(self):
        for old, new, own, ends_sessions, granted in TRANSITIONS:
            label = f"{old} -> {new}, own password: {own}"
            emp = self.employee(old, own)
            session = self.tokens(emp)
            self.change(emp, custom_authentication=new)

            self.assertEqual(self.field(emp, "custom_employee_has_signed_up"), 1, label)  # sign-up kept
            self.assertTrue(can_log_in(emp.user, emp.password), label)  # credential kept
            self.assertEqual(self.token_status(session), "Revoked" if ends_sessions else "Active", label)
            body = self.policy(emp)
            self.assertIs(body["employee_has_signed_up"], True, label)
            self.assertIs(body["employee_has_existing_password"], own, label)
            self.assertEqual(body["sign_in_policy"], get_login_policies({"custom_authentication": new})["sign_in_policy"], label)
            self.assertIs(body["password_setup_pending"], granted, label)
            self.assertIs(body["otp_verified_password_setup"], granted, label)  # switch off: only the grant opens setup

    def test_moved_to_password_without_one_creates_it_and_signs_in(self):
        emp = self.employee(OTP, own_password=False)
        self.change(emp, custom_authentication=PASSWORD)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=emp.password))
        self.assertEqual((status, body["message"]), (401, "Invalid password"))  # the placeholder never signs in
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.new_password))
        self.assertEqual((status, body["data"]["employee_id"]), (200, emp.name))
        self.assertEqual(self.field(emp, "custom_password_setup_pending"), 0)  # the grant is used up
        body = self.policy(emp)
        self.assertEqual(
            (body["employee_has_existing_password"], body["password_setup_pending"], body["otp_verified_password_setup"]),
            (True, False, False),
        )
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=self.new_password))[0], 200)
        self.assertTrue(can_log_in(emp.user, self.new_password))

    def test_moved_to_both_without_a_password_needs_both_factors_after_setup(self):
        emp = self.employee(OTP, own_password=False)
        self.change(emp, custom_authentication=BOTH)
        status, _ = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.new_password))
        self.assertEqual(status, 200)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=self.new_password))
        self.assertEqual((status, body["message"]), (400, "OTP is required"))
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=self.new_password, otp=self.fresh_otp(emp)))[0], 200)
        # Now that a password exists, an OTP alone can never replace it, switch or not.
        frappe.db.set_single_value("Checkin App Setting", "allow_in_app_password_setup", 1)
        self.assertIs(self.policy(emp)["otp_verified_password_setup"], False)
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.other_password))
        self.assertEqual((status, body["data"]["message"]), (403, "Password setup is not available"))
        self.assertTrue(can_log_in(emp.user, self.new_password))

    def test_password_to_otp_keeps_the_erp_password(self):
        emp = self.employee(PASSWORD, own_password=True)
        self.change(emp, custom_authentication=OTP)
        status, _ = reply(sign_in_api(mobile_no=emp.mobile, otp=self.fresh_otp(emp), password=self.device_password))
        self.assertEqual(status, 200)
        self.assertTrue(can_log_in(emp.user, emp.password))

    def test_password_to_both_needs_the_otp_too(self):
        emp = self.employee(PASSWORD, own_password=True)
        self.change(emp, custom_authentication=BOTH)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=emp.password))
        self.assertEqual((status, body["message"]), (400, "OTP is required"))
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=emp.password, otp=self.fresh_otp(emp)))[0], 200)

    def test_both_to_password_keeps_the_session_and_the_password(self):
        emp = self.employee(BOTH, own_password=True)
        session = self.tokens(emp)
        self.change(emp, custom_authentication=PASSWORD)
        self.assertEqual(self.token_status(session), "Active")
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=emp.password))[0], 200)

    def test_grant_never_replaces_a_chosen_password(self):
        emp = self.employee(PASSWORD, own_password=True)
        frappe.db.set_value("Employee", emp.name, "custom_password_setup_pending", 1)  # even if HR ticks it
        self.assertIs(self.policy(emp)["otp_verified_password_setup"], False)
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.new_password))
        self.assertEqual((status, body["data"]["message"]), (403, "Password setup is not available"))
        self.assertTrue(can_log_in(emp.user, emp.password))

    def test_grant_does_not_reach_admin_accounts(self):
        emp = self.make(OTP, roles=("Employee", "System Manager"))
        self.change(emp, custom_authentication=PASSWORD)
        body = self.policy(emp)
        self.assertEqual((body["password_setup_pending"], body["otp_verified_password_setup"]), (False, False))
        status, _ = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.new_password))
        self.assertEqual(status, 403)

    def test_employee_who_never_signed_up_still_signs_up(self):
        emp = self.employee(OTP, own_password=False, signed_up=0)
        self.change(emp, custom_authentication=PASSWORD)
        self.assertEqual(self.field(emp, "custom_employee_has_signed_up"), 0)
        body = self.policy(emp)
        self.assertEqual((body["employee_has_signed_up"], body["password_setup_pending"]), (False, False))
        status, _ = reply(sign_up_api(mobile_no=emp.mobile, otp=self.fresh_otp(emp), password=self.new_password))
        self.assertEqual(status, 200)
        self.assertEqual(
            (self.field(emp, "custom_user_created_password"), self.field(emp, "custom_password_setup_pending")), (1, 0)
        )
        self.assertTrue(can_log_in(emp.user, self.new_password))

    def test_inactive_employee_stays_blocked(self):
        emp = self.employee(OTP, own_password=False)
        session = self.tokens(emp)
        self.change(emp, custom_authentication=PASSWORD, status="Inactive")
        self.assertEqual(self.token_status(session), "Revoked")
        self.assertEqual(reply(get_employee_login_policy(mobile=emp.mobile))[0], 404)
        status, _ = reply(create_new_password(mobile_no=emp.mobile, otp=TEST_OTP, new_password=self.new_password))
        self.assertEqual(status, 404)

    def test_disabled_user_stays_blocked(self):
        emp = self.employee(OTP, own_password=False)
        self.change(emp, custom_authentication=PASSWORD)
        user = frappe.get_doc("User", emp.user)
        user.enabled = 0
        user.save()
        body = self.policy(emp)
        self.assertEqual((body["password_setup_pending"], body["otp_verified_password_setup"]), (False, False))
        status, _ = reply(create_new_password(mobile_no=emp.mobile, otp=self.fresh_otp(emp), new_password=self.new_password))
        self.assertEqual(status, 403)


class TestHighSecurity(TransitionTestCase):
    def test_turning_it_on_ends_sessions_in_every_mode(self):
        for mode in (PASSWORD, OTP, OPTIONAL, BOTH):
            emp = self.employee(mode, own_password=mode != OTP)
            session = self.tokens(emp)
            self.change(emp, custom_high_security=1)
            self.assertEqual(self.token_status(session), "Revoked", mode)

    def test_turning_it_off_keeps_sessions_and_needs_no_cold_boot(self):
        emp = self.employee(OTP, own_password=False, high_security=1)
        session = self.tokens(emp)
        self.change(emp, custom_high_security=0)
        self.assertEqual(self.token_status(session), "Active")
        status, body = reply(sign_in_api(mobile_no=emp.mobile, otp=TEST_OTP, password=self.device_password, login_type="cold_boot"))
        self.assertEqual((status, body["message"]), (400, "No cold boot verification required for this employee"))

    def test_cold_boot_is_never_weaker_than_sign_in(self):
        for mode in (PASSWORD, OTP, OPTIONAL, BOTH):
            policies = get_login_policies({"custom_authentication": mode, "custom_high_security": 1})
            self.assertEqual(policies["cold_boot_policy"], policies["sign_in_policy"], mode)

    def test_both_needs_the_otp_on_cold_boot(self):
        emp = self.employee(BOTH, own_password=True, high_security=1)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=emp.password, login_type="cold_boot"))
        self.assertEqual((status, body["message"]), (400, "OTP is required"))
        status, body = reply(otp_generate_for_sign_in(mobile_no=emp.mobile, password=emp.password, login_type="cold_boot"))
        self.assertEqual((status, body["message"]), (200, "OTP sent successfully"))
        self.assertNotIn("data", body)  # the password alone gets no token
        status, _ = reply(sign_in_api(mobile_no=emp.mobile, password=emp.password, otp=TEST_OTP, login_type="cold_boot"))
        self.assertEqual(status, 200)


class TestAdminWorkflows(TransitionTestCase):
    def assert_moved(self, emp, session):
        self.assertEqual(
            (self.field(emp, "custom_employee_has_signed_up"), self.field(emp, "custom_password_setup_pending"),
             self.token_status(session)),
            (1, 1, "Revoked"),
        )

    def test_rest_and_bulk_edit_apply_the_rules(self):
        from frappe.client import set_value
        from frappe.desk.doctype.bulk_update.bulk_update import submit_cancel_or_update_docs

        rest = self.employee(OTP, own_password=False)
        session = self.tokens(rest)
        set_value("Employee", rest.name, "custom_authentication", PASSWORD)  # what a REST update runs
        self.assert_moved(rest, session)

        bulk = self.employee(OTP, own_password=False)
        session = self.tokens(bulk)
        with patch("frappe.publish_progress"):
            failed = submit_cancel_or_update_docs("Employee", [bulk.name], action="update", data={"custom_authentication": BOTH})
        self.assertEqual(failed, [])
        self.assert_moved(bulk, session)

    def test_raw_updates_skip_the_rules(self):
        emp = self.employee(OTP, own_password=False)
        session = self.tokens(emp)
        frappe.db.set_value("Employee", emp.name, "custom_authentication", PASSWORD)
        frappe.db.sql("update `tabEmployee` set custom_high_security = 1 where name = %s", emp.name)
        self.assertEqual(
            (self.field(emp, "custom_employee_has_signed_up"), self.field(emp, "custom_password_setup_pending"),
             self.token_status(session)),
            (1, 0, "Active"),
        )


class TestSignUpCredentials(TransitionTestCase):
    def test_sign_up_checks_an_existing_password_instead_of_replacing_it(self):
        emp = self.employee(PASSWORD, own_password=True, signed_up=0)  # HR unticked "Employee has signed up"
        status, body = reply(sign_up_api(mobile_no=emp.mobile, otp=self.fresh_otp(emp), password=self.other_password))
        self.assertEqual((status, body["message"]), (401, "Invalid password"))
        self.assertTrue(can_log_in(emp.user, emp.password))
        self.assertEqual(reply(sign_up_api(mobile_no=emp.mobile, otp=TEST_OTP, password=emp.password))[0], 200)
        self.assertTrue(can_log_in(emp.user, emp.password))

    def test_otp_only_sign_up_never_sets_a_password(self):
        emp = self.employee(OTP, own_password=False, signed_up=0)
        status, _ = reply(sign_up_api(mobile_no=emp.mobile, otp=self.fresh_otp(emp), password=self.new_password))
        self.assertEqual(status, 200)
        self.assertFalse(can_log_in(emp.user, self.new_password))
        self.assertEqual(self.field(emp, "custom_user_created_password"), 0)


class TestPasswordSetupCommit(TransitionTestCase):
    def test_a_saved_password_is_never_reported_as_failed(self):
        emp = self.employee(OTP, own_password=False)
        self.change(emp, custom_authentication=PASSWORD)
        code = self.fresh_otp(emp)
        with (
            patch("frappe.sessions.clear_sessions", side_effect=RuntimeError("injected")),
            patch.object(auth_core, "log_failure") as logged,
        ):
            status, body = reply(create_new_password(mobile_no=emp.mobile, otp=code, new_password=self.new_password))
        self.assertEqual((status, body["data"]["status"]), (200, "success"))
        logged.assert_called_once()
        self.assertTrue(can_log_in(emp.user, self.new_password))


class TestRepairOfOldResets(TransitionTestCase):
    def versioned_save(self, emp, **values):
        doc = frappe.get_doc("Employee", emp.name)
        doc.update(values)
        doc.save(ignore_version=False)  # tests skip change history unless asked

    def old_hook_save(self, emp, new):
        """What commit 23d3f1c did: untick sign-up in the same save as the change."""
        with patch.object(auth_core, "on_authentication_change"):  # the old code had no grant
            self.versioned_save(emp, custom_authentication=new, custom_employee_has_signed_up=0)

    def test_restores_sign_ups_the_old_hook_reset(self):
        kept = self.employee(PASSWORD, own_password=True)
        self.old_hook_save(kept, OTP)
        stuck = self.employee(OTP, own_password=False)
        self.old_hook_save(stuck, PASSWORD)
        manual = self.employee(PASSWORD, own_password=True)
        self.versioned_save(manual, custom_employee_has_signed_up=0)  # HR's own untick: left alone
        again = self.employee(OTP, own_password=False)
        self.old_hook_save(again, OPTIONAL)
        frappe.db.set_value("Employee", again.name, "custom_employee_has_signed_up", 1)  # signed up again since

        self.assertGreaterEqual(auth_audit.run()["active_not_signed_up_with_own_password"], 2)
        dry = auth_audit.restore_signups_reset_by_policy_change()
        self.assertEqual(self.field(kept, "custom_employee_has_signed_up"), 0)  # a dry run changes nothing
        self.assertEqual((dry["restored"], dry["first_password_granted"]), (2, 1))
        auth_audit.restore_signups_reset_by_policy_change(dry_run=False)
        self.assertEqual(self.field(kept, "custom_employee_has_signed_up"), 1)
        self.assertEqual(
            (self.field(stuck, "custom_employee_has_signed_up"), self.field(stuck, "custom_password_setup_pending")), (1, 1)
        )
        self.assertEqual(self.field(manual, "custom_employee_has_signed_up"), 0)
        self.assertIs(self.policy(stuck)["password_setup_pending"], True)
