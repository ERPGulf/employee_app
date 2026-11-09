# Integration tests for the auth remediation. They need a site with erpnext, hrms
# and employee_app installed, and Redis:
#   bench --site <test-site> run-tests --module employee_app.tests.test_auth_remediation

import json
import random
from unittest.mock import patch

import frappe
from frappe.core.doctype.user.user import User
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import update_password
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from employee_app import auth_core
from employee_app.authentication import (
    generate_and_send_otp,
    get_employee_login_policy,
    refresh_employee_token,
    sign_up_api,
)
from employee_app.gauth import create_new_password
from employee_app.sign_in import sign_in_api

test_dependencies = ["Employee"]

TEST_OTP = "246810"
LEGACY = "egf_Legacy1"  # a managed placeholder that a pre-remediation sign-in left as the login password
CHOSEN = "Chosen#Pass-2026"


def reply(response):
    return response.status_code, json.loads(response.get_data())


def can_log_in(user, password):
    """The credential check behind the ERP website's /login."""
    found = User.find_by_credentials(user, password)
    return bool(found and found.is_authenticated and found.enabled)


class AuthTestCase(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")  # the previous class may have left another user in session
        for patcher in (
            patch("employee_app.user_qa_code.create_qr_code"),  # QR files are not under test
            # Endpoints commit; keep everything in the test transaction that the class rolls back.
            patch.object(frappe.db, "commit"),
            # A fixed OTP and no WhatsApp: auth_core only allows this on developer-mode sites.
            patch.dict(frappe.conf, {"developer_mode": 1, "employee_app_test_otp": TEST_OTP}),
            # ERPNext's test setup sets the country to United States; the numbers below are Saudi.
            patch("employee_app.auth_core._region", return_value="SA"),
        ):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        if not frappe.db.exists("OAuth Client", {"app_name": "AuthTestApp"}):
            frappe.get_doc({
                "doctype": "OAuth Client",
                "app_name": "AuthTestApp",
                "scopes": "all openid",
                "default_redirect_uri": "http://localhost",
            }).insert(ignore_permissions=True)

    def setUp(self):
        # FrappeTestCase rolls back once per class, so reset shared state per test.
        frappe.cache().delete_keys("employee_app:auth:")
        frappe.set_user("Administrator")
        frappe.db.set_single_value("Checkin App Setting", "allow_in_app_password_setup", 1)

    def make(self, authentication="Password Authentication", signed_up=1, own_password=0,
             high_security=0, mobile=None, password=LEGACY, roles=("Employee",)):
        user = f"auth-{frappe.generate_hash(length=10)}@example.com"
        frappe.get_doc({
            "doctype": "User", "email": user, "first_name": "Auth", "send_welcome_email": 0,
            "roles": [{"role": role} for role in roles],
        }).insert()
        mobile = mobile or f"05{random.randint(10**7, 10**8 - 1)}"
        employee = frappe.get_doc({
            "doctype": "Employee", "naming_series": "EMP-", "first_name": "Auth", "gender": "Female",
            "date_of_birth": "1990-05-08", "date_of_joining": "2013-01-01", "company": "_Test Company",
            "status": "Active", "user_id": user, "cell_number": mobile,
            "custom_authentication": authentication, "custom_high_security": high_security,
            "custom_employee_has_signed_up": signed_up, "custom_user_created_password": own_password,
        }).insert()
        if password:
            update_password(user, password)
        return frappe._dict(name=employee.name, user=user, mobile=mobile)

    def otp(self, emp):
        status, _ = reply(generate_and_send_otp(mobile_no=emp.mobile))
        self.assertEqual(status, 200)
        return TEST_OTP

    def tokens(self, emp):
        return auth_core.issue_app_tokens(emp.user)

    def token_status(self, token):
        return frappe.db.get_value("OAuth Bearer Token", token["access_token"], "status")


class TestLookup(AuthTestCase):
    def test_every_format_of_one_number_finds_the_employee(self):
        emp = self.make(mobile="0551234567")
        for raw in ("+966551234567", "966551234567", "00966551234567", "551234567", "055 123 4567"):
            self.assertEqual(auth_core.find_employee(raw).name, emp.name, raw)

    def test_same_last_digits_in_another_country_is_not_a_match(self):
        self.make(mobile="+971559876543")
        self.assertIsNone(auth_core.find_employee("0559876543"))

    def test_shared_number_is_refused(self):
        self.make(mobile="0557777777")
        self.make(mobile="+966557777777")
        self.assertIsNone(auth_core.find_employee("0557777777"))

    def test_inactive_employee_is_not_found(self):
        emp = self.make()
        frappe.db.set_value("Employee", emp.name, "status", "Inactive")
        self.assertIsNone(auth_core.find_employee(emp.mobile))

    def test_foreign_number_stored_without_plus(self):
        emp = self.make(mobile="971559876543")
        self.assertEqual(auth_core.find_employee("+971559876543").name, emp.name)


class TestPolicyPromise(AuthTestCase):
    def policy(self, emp):
        status, body = reply(get_employee_login_policy(mobile=emp.mobile))
        self.assertEqual(status, 200)
        self.assertIsInstance(body["otp_verified_password_setup"], bool)
        self.assertIsInstance(body["employee_has_existing_password"], bool)
        self.assertIsInstance(body["employee_has_signed_up"], bool)
        return body["otp_verified_password_setup"]

    def test_promise_by_employee_state(self):
        cases = {
            "moved to Password, never set one": (self.make("Password Authentication"), True),
            "password user": (self.make("Password Authentication", own_password=1, password=CHOSEN), True),
            "Optional, no password": (self.make("Optional"), True),
            "Both, never set one": (self.make("Both"), True),
            "Both, own password": (self.make("Both", own_password=1, password=CHOSEN), False),
            "OTP only": (self.make("OTP Authentication"), False),
            "not signed up": (self.make(signed_up=0), False),
            "privileged user": (self.make(roles=("Employee", "System Manager")), False),
        }
        for label, (emp, expected) in cases.items():
            self.assertEqual(self.policy(emp), expected, label)

    def test_switch_off_withdraws_the_promise(self):
        emp = self.make()
        frappe.db.set_single_value("Checkin App Setting", "allow_in_app_password_setup", 0)
        self.assertFalse(self.policy(emp))

    def test_endpoint_refuses_whenever_the_promise_is_false(self):
        for emp in (self.make("OTP Authentication"), self.make("Both", own_password=1, password=CHOSEN),
                    self.make(signed_up=0), self.make(roles=("Employee", "System Manager"))):
            self.assertFalse(self.policy(emp))
            status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.otp(emp), new_password="N3w-Strong#Pass"))
            self.assertEqual((status, body["data"]["message"]), (403, "Password setup is not available"))


class TestPasswordSetup(AuthTestCase):
    def test_stuck_employee_sets_a_password_that_works_on_the_erp_website(self):
        emp = self.make("Password Authentication")  # moved from OTP, login password is a placeholder
        old_session = self.tokens(emp)
        roles_before = sorted(frappe.get_roles(emp.user))
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.otp(emp), new_password="N3w-Strong#Pass"))

        self.assertEqual(status, 200)
        self.assertNotIn("status", body)  # frozen contract: everything nested under data
        self.assertEqual(body["data"]["status"], "success")
        self.assertEqual(body["data"]["employee_id"], emp.name)
        self.assertTrue(can_log_in(emp.user, "N3w-Strong#Pass"))
        self.assertFalse(can_log_in(emp.user, LEGACY))
        self.assertEqual(self.token_status(old_session), "Revoked")
        employee = frappe.db.get_value("Employee", emp.name, ["custom_authentication", "custom_user_created_password"], as_dict=True)
        self.assertEqual(employee.custom_authentication, "Password Authentication")  # policy unchanged
        self.assertEqual(employee.custom_user_created_password, 1)
        self.assertEqual(sorted(frappe.get_roles(emp.user)), roles_before)  # no access granted

    def test_refusals_keep_the_password(self):
        emp = self.make()
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp="000000", new_password="N3w-Strong#Pass"))
        self.assertEqual((status, body["data"]["message"]), (401, "Invalid or expired OTP"))
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=TEST_OTP, new_password="egf_abc123"))
        self.assertEqual((status, body["data"]["message"]), (400, "Please choose a different password"))
        frappe.db.set_single_value("Checkin App Setting", "allow_in_app_password_setup", 0)
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=self.otp(emp), new_password="N3w-Strong#Pass"))
        self.assertEqual(status, 403)
        self.assertTrue(can_log_in(emp.user, LEGACY))

    def test_refused_setup_does_not_spend_the_otp(self):
        emp = self.make("OTP Authentication")
        code = self.otp(emp)
        status, _ = reply(create_new_password(mobile_no=emp.mobile, otp=code, new_password="N3w-Strong#Pass"))
        self.assertEqual(status, 403)
        status, _ = reply(sign_in_api(mobile_no=emp.mobile, otp=code, password="egf_Device1"))
        self.assertEqual(status, 200)

    def test_one_otp_sets_one_password(self):
        emp = self.make()
        code = self.otp(emp)
        self.assertEqual(reply(create_new_password(mobile_no=emp.mobile, otp=code, new_password="N3w-Strong#Pass"))[0], 200)
        status, body = reply(create_new_password(mobile_no=emp.mobile, otp=code, new_password="An0ther#Pass"))
        self.assertEqual((status, body["data"]["message"]), (401, "Invalid or expired OTP"))


class TestMobileSignInKeepsErpPasswords(AuthTestCase):
    def test_otp_sign_in_never_changes_the_login_password(self):
        emp = self.make("OTP Authentication", password=CHOSEN)  # HR set an ERP password in Desk
        status, body = reply(sign_in_api(mobile_no=emp.mobile, otp=self.otp(emp), password="egf_NewDev1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["employee"]["id"], emp.name)
        for key in ("access_token", "refresh_token", "expires_in", "token_type", "scope"):
            self.assertIn(key, body["data"]["token"])
        self.assertTrue(can_log_in(emp.user, CHOSEN))
        self.assertFalse(can_log_in(emp.user, "egf_NewDev1"))

    def test_otp_is_single_use(self):
        emp = self.make("OTP Authentication")
        code = self.otp(emp)
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, otp=code, password="egf_Dev1"))[0], 200)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, otp=code, password="egf_Dev1"))
        self.assertEqual((status, body["message"]), (401, "Invalid or expired OTP"))

    def test_placeholder_is_never_accepted_as_a_password(self):
        emp = self.make("Password Authentication")  # login password is still LEGACY
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=LEGACY))
        self.assertEqual((status, body["message"]), (401, "Invalid password"))

    def test_password_user_signs_in(self):
        emp = self.make("Password Authentication", own_password=1, password=CHOSEN)
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=CHOSEN))[0], 200)

    def test_wrong_passwords_lock_the_employee(self):
        emp = self.make("Password Authentication", own_password=1, password=CHOSEN)
        for _ in range(auth_core.LOCK_AFTER):
            self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password="wrong-Pass1"))[0], 401)
        status, body = reply(sign_in_api(mobile_no=emp.mobile, password=CHOSEN))
        self.assertEqual((status, body), (429, {"status": "error", "message": auth_core.TOO_MANY}))

    def test_disabled_user_gets_no_token(self):
        emp = self.make("OTP Authentication")
        code = self.otp(emp)
        frappe.db.set_value("User", emp.user, "enabled", 0)
        status, _ = reply(sign_in_api(mobile_no=emp.mobile, otp=code, password="egf_Dev1"))
        self.assertEqual(status, 401)


class TestSignUp(AuthTestCase):
    def test_placeholder_sign_up_leaves_the_login_password_alone(self):
        emp = self.make("OTP Authentication", signed_up=0, password=CHOSEN)
        status, _ = reply(sign_up_api(mobile_no=emp.mobile, otp=self.otp(emp), password="egf_Dev1"))
        self.assertEqual(status, 200)
        self.assertTrue(can_log_in(emp.user, CHOSEN))
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "custom_employee_has_signed_up"), 1)

    def test_chosen_password_at_sign_up_is_saved(self):
        emp = self.make("Password Authentication", signed_up=0)
        self.assertEqual(reply(sign_up_api(mobile_no=emp.mobile, otp=self.otp(emp), password=CHOSEN))[0], 200)
        self.assertTrue(can_log_in(emp.user, CHOSEN))
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "custom_user_created_password"), 1)

    def test_sign_up_never_sets_an_admin_password(self):
        emp = self.make("Password Authentication", signed_up=0, password=CHOSEN, roles=("Employee", "System Manager"))
        status, body = reply(sign_up_api(mobile_no=emp.mobile, otp=self.otp(emp), password="Takeover#Pass1"))
        self.assertEqual((status, body["message"]), (401, "Invalid password"))
        self.assertTrue(can_log_in(emp.user, CHOSEN))
        self.assertEqual(reply(sign_up_api(mobile_no=emp.mobile, otp=TEST_OTP, password=CHOSEN))[0], 200)
        self.assertTrue(can_log_in(emp.user, CHOSEN))

    def test_second_sign_up_is_refused(self):
        emp = self.make("Both", own_password=1, password=CHOSEN)
        status, body = reply(sign_up_api(mobile_no=emp.mobile, otp=self.otp(emp), password="Takeover#Pass1"))
        self.assertEqual((status, body["message"]), (409, "Employee has already signed up"))
        self.assertTrue(can_log_in(emp.user, CHOSEN))

    def test_no_plaintext_is_stored(self):
        if not frappe.db.has_column("Employee", "custom_employee_password"):
            return
        emp = self.make("Password Authentication", signed_up=0)
        reply(sign_up_api(mobile_no=emp.mobile, otp=self.otp(emp), password=CHOSEN))
        self.assertFalse(frappe.db.get_value("Employee", emp.name, "custom_employee_password"))


class TestOtpDelivery(AuthTestCase):
    def test_reply_never_contains_the_otp(self):
        emp = self.make("OTP Authentication")
        status, body = reply(generate_and_send_otp(mobile_no=emp.mobile))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "success", "message": "OTP sent successfully", "otp_expires_in": 300})

    def test_second_send_within_a_minute_is_throttled(self):
        emp = self.make("OTP Authentication")
        self.otp(emp)
        status, body = reply(generate_and_send_otp(mobile_no=emp.mobile))
        self.assertEqual((status, body), (429, {"status": "error", "message": auth_core.TOO_MANY}))


class TestSessions(AuthTestCase):
    def test_refresh_token_must_be_a_string(self):
        token = self.tokens(self.make())  # the newest token on the site
        for value in (["like", "%"], ["!=", ""], {"like": "%"}):
            self.assertEqual(reply(refresh_employee_token(value))[0], 401)
        self.assertEqual(self.token_status(token), "Active")

    def test_locks_survive_a_full_cache_clear(self):
        emp = self.make("Password Authentication", own_password=1, password=CHOSEN)
        for _ in range(auth_core.LOCK_AFTER):
            reply(sign_in_api(mobile_no=emp.mobile, password="wrong-Pass1"))
        frappe.clear_cache()  # ERPNext does this on every Employee save
        self.assertEqual(reply(sign_in_api(mobile_no=emp.mobile, password=CHOSEN))[0], 429)

    def test_refresh_works_once_and_reuse_ends_every_session(self):
        emp = self.make()
        first = self.tokens(emp)
        status, body = reply(refresh_employee_token(first["refresh_token"]))
        self.assertEqual(status, 200)
        second = body["data"]["token"]
        self.assertEqual(reply(refresh_employee_token(first["refresh_token"]))[0], 401)
        self.assertEqual(self.token_status(second), "Revoked")

    def test_high_security_on_ends_sessions(self):
        emp = self.make()
        token = self.tokens(emp)
        employee = frappe.get_doc("Employee", emp.name)
        employee.custom_high_security = 1
        employee.save()
        self.assertEqual(self.token_status(token), "Revoked")

    def test_leaving_active_ends_sessions(self):
        emp = self.make()
        token = self.tokens(emp)
        employee = frappe.get_doc("Employee", emp.name)
        employee.status = "Inactive"
        employee.save()
        self.assertEqual(self.token_status(token), "Revoked")


class TestServiceGate(AuthTestCase):
    def call_gate(self, path):
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = Request(EnvironBuilder(path=path, headers={"Authorization": "Bearer x"}).get_environ())
        try:
            return auth_core.service_gate()
        finally:
            frappe.local.request = previous

    def test_service_token_is_limited_to_pre_login_methods(self):
        service = self.make().user
        frappe.db.set_single_value("Checkin App Setting", "user", service)
        frappe.set_user(service)
        self.assertIsNone(self.call_gate("/api/method/employee_app.sign_in.sign_in_api"))
        self.assertIsNone(self.call_gate("/api/resource/Employee"))  # log-only by default
        with patch.dict(frappe.conf, {"employee_app_service_gate": "enforce"}):
            self.assertIsNone(self.call_gate("/api/method/employee_app.gauth.create_new_password"))
            for path in ("/api/resource/Employee", "/api/method/employee_app.attendance_api.error_log",
                         "/api/v2/document/User/Administrator"):
                with self.assertRaises(frappe.PermissionError):
                    self.call_gate(path)

    def test_other_users_are_not_gated(self):
        frappe.db.set_single_value("Checkin App Setting", "user", "Administrator")
        frappe.set_user(self.make().user)
        with patch.dict(frappe.conf, {"employee_app_service_gate": "enforce"}):
            self.assertIsNone(self.call_gate("/api/resource/Employee"))
