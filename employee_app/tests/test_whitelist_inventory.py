# Fails when a whitelisted method appears that nobody reviewed, or a removed one comes back.
#   bench --site <test-site> run-tests --module employee_app.tests.test_whitelist_inventory

import importlib

import frappe
from frappe.tests.utils import FrappeTestCase

# "Who may call it, and how it authorizes." Service token = the app's shared token
# from master_token; auth_core.service_gate limits it to auth_core.PRE_LOGIN_METHODS.
REVIEWED = {
    "employee_app.authentication.master_token": "guest; issues the service token (retire: item 4)",
    "employee_app.authentication.get_employee_login_policy": "service token; per-IP limit; reveals policy only",
    "employee_app.authentication.generate_and_send_otp": "service token; per-IP and per-employee send limits",
    "employee_app.authentication.sign_up_api": "service token; OTP; first sign-up only",
    "employee_app.authentication.otp_generate_for_cold_boot": "service token; as otp_generate_for_sign_in",
    "employee_app.authentication.cold_boot_api": "service token; as sign_in_api",
    "employee_app.authentication.refresh_employee_token": "any token; refresh token, single use, reuse revokes all",
    "employee_app.sign_in.otp_generate_for_sign_in": "guest; password with lockout, or sends an OTP",
    "employee_app.sign_in.sign_in_api": "service token; OTP and/or password with lockout",
    "employee_app.gauth.create_new_password": "service token; POST; OTP; auth_core.password_setup_allowed",
    "employee_app.gauth.create_refresh_token": "guest; refresh token, single use, reuse revokes all",
    "employee_app.gauth.generate_token_secure": "guest; username + password via LoginManager (Frappe login tracker)",
    "employee_app.gauth.generate_custom_token_for_employee": "login; OAuth client user's password",
    "employee_app.gauth.generate_custom_token": "login; disabled, always 500",
    "employee_app.gauth.getToken2": "login; no-op",
    "employee_app.gauth.whoami": "login; returns the session user",
}

# Business APIs from before the remediation, not yet reviewed one by one. They need an
# employee token; in enforce mode the service token can't reach them. Review, then move up.
NOT_YET_REVIEWED = {
    *(f"employee_app.attendance_api.{name}" for name in (
        "insert_new_trip", "close_the_trip", "get_latest_open_trip", "contract_list", "vehicle_list",
        "employee_checkin", "error_log", "error_log_seen", "list_employee", "Employee_Checkin", "upload_file",
        "_get_compound_code_from_coordinates", "add_log_based_on_employee_field", "employee",
        "get_employee_data", "get_attendance_details", "is_employee_shift_enabled", "get_log_type",
        "sync_all_employee_session_windows", "get_expense_claims", "create_expense_claim",
        "create_leave_application", "get_total_hours", "get_monthly_hours", "get_server_time",
        "get_shortcut_1", "get_shortcut_2", "get_shortcut_3", "qr_code", "get_leave_type", "get_notification",
        "mark_notification_as_read", "get_expense_claim_type", "create_complaint", "Employee_break",
        "get_last_log", "get_employee_working_hours", "get_break_hours", "get_today_breaks",
        "override_working_hours", "get_monthly_break_hours", "get_notification1", "add_diagnostic_message",
        "get_loan_product", "create_loan_application", "add_offline_employee_checkins", "get_attendance_history",
    )),
    *(f"employee_app.material_request.{name}" for name in (
        "warehouse_list", "get_items", "create_stock_entry", "list_stock_entries", "update_stock_entry",
        "delete_stock_entry", "list_items", "make_stock_entry", "get_item_uom", "list_items_search", "on_submit",
        "create_stock_reconciliation_doc", "get_stock", "create_material_request", "list_material_requests",
        "items", "items_to_request",
    )),
    *(f"employee_app.employee_list.{name}" for name in (
        "list_attendance_request", "list_loan_application", "list_leave_application", "add_employee_app_log",
        "list_user_roles_and_permissions",
    )),
    *(f"employee_app.gauth.{name}" for name in (
        "create_attendence_request", "validate_location_restriction", "get_tasks", "salary_advance_request",
        "create_overtime_request", "get_employee_overtime_requests", "employee_checkin_setting",
    )),
    "employee_app.bulk_location.set_employee_locations",
    "employee_app.employee_app_for_erpnext.doctype.employee_resignation.employee_resignation.create_employee_resignation",
}

# Removed by the remediation: they must never be callable again.
REMOVED = {
    "employee_app.gauth.request_login_otp",
    "employee_app.gauth.login_with_otp",
    "employee_app.gauth.resend_otp",
    "employee_app.gauth.validate_old_password",
    "employee_app.gauth.verify_otp",
    "employee_app.authentication.set_employee_password",
    "employee_app.authentication.sync_user_password_to_employee",
}


class TestWhitelistInventory(FrappeTestCase):
    def whitelisted(self):
        for module in {name.rpartition(".")[0] for name in set(REVIEWED) | NOT_YET_REVIEWED}:
            importlib.import_module(module)  # registers its whitelisted methods
        return {
            f"{fn.__module__}.{fn.__qualname__}"
            for fn in frappe.whitelisted
            if fn.__module__.startswith("employee_app.")
        }

    def test_every_whitelisted_method_is_reviewed(self):
        self.assertEqual(self.whitelisted() - REVIEWED.keys() - NOT_YET_REVIEWED, set())

    def test_removed_methods_stay_removed(self):
        self.assertEqual(self.whitelisted() & REMOVED, set())

    def test_service_token_allowlist_is_reviewed(self):
        from employee_app.auth_core import PRE_LOGIN_METHODS

        self.assertEqual(PRE_LOGIN_METHODS - REVIEWED.keys(), set())
