#Employee app from ERPGulf.com

app_name = "employee_app"
app_title = "Employee app for ERPNext"
app_publisher = "ERPGulf.com"
app_description = "Attendance and related submissions through mobile APP"
app_email = "support@ERPGulf.com"
app_license = "MIT"
required_apps = ["hrms"]
doctype_list_js = {"Employee": "public/js/employee_list.js"}
app_include_js = ["/assets/employee_app/js/monthly_attendance_sheet.js"]
fixtures = [
    {"dt": "Custom Field", "filters": {"module": "Employee app for ERPNext"}},
    {
        "dt": "Client Script",
        "filters": {"module": "Employee app for ERPNext"},
    },
    {"dt": "Leave Type", "filters": [["name", "in", ["Annual", "Remote", "Out Of Office"]]]}
]

doc_events = {
    "Employee": {
        "on_update": [
            "employee_app.user_qa_code.create_qr_code",
            "employee_app.auth_core.on_employee_security_change",
        ],
        "on_trash": "employee_app.user_qa_code.delete_qr_code_file",
        "validate": [
            "employee_app.gauth.validate_location_restriction",
            "employee_app.auth_core.reset_signup_on_authentication_change",
        ],
    },
    "Employee Checkin": {
        "after_insert": "employee_app.attendance_api.employee_checkin_handler"
    },
     "Attendance": {
        "validate": "employee_app.attendance_api.override_working_hours"
    },
    "Employee Location": {
        "validate": "employee_app.gauth.validate_coordinates"
    },
    "User": {
        "on_update": "employee_app.auth_core.on_user_disabled",
        "after_insert": "employee_app.TwoFA.login.on_user_after_insert"
    },
    "System Settings": {
        "validate": "employee_app.TwoFA.policy.validate_system_settings"
    }
}
doctype_js = {
    "Employee Notification": "public/fetch_employee.js",
    "System Settings": "public/js/2fa/system_settings.js",
}

# Runs after the bearer token is resolved: keeps the app's shared service token
# on the pre-login methods (log-only until site_config sets employee_app_service_gate).
auth_hooks = ["employee_app.auth_core.service_gate"]

# OTPs, lockouts and throttle counters must survive frappe.clear_cache(), which
# ERPNext calls on every Employee save.
persistent_cache_keys = ["employee_app:auth:*"]

# On-screen QR enrolment for two-factor sign-in (employee_app/twofa.py)
before_login = ["employee_app.TwoFA.login.install"]
after_install = "employee_app.TwoFA.setup.set_otp_issuer"
after_migrate = ["employee_app.TwoFA.setup.set_otp_issuer"]
on_login = ["employee_app.TwoFA.login.on_login"]
override_whitelisted_methods = {
    "frappe.twofactor.reset_otp_secret": "employee_app.TwoFA.login.reset_otp_secret"
}
web_include_js = ["/assets/employee_app/js/2fa/login.js"]
