#Employee app from ERPGulf.com

app_name = "employee_app"
app_title = "Employee app for ERPNext"
app_publisher = "ERPGulf.com"
app_description = "Attendance and related submissions through mobile APP"
app_email = "support@ERPGulf.com"
app_license = "MIT"

required_apps = ["hrms"]

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
        "on_update": "employee_app.user_qa_code.create_qr_code",
        "on_trash": "employee_app.user_qa_code.delete_qr_code_file",
        "validate": "employee_app.gauth.validate_location_restriction"
    },
    "Employee Checkin": {
        "after_insert": "employee_app.attendance_api.employee_checkin_handler"
    },
     "Attendance": {
        "validate": "employee_app.attendance_api.override_working_hours"
    },
    "Employee Location": {
        "validate": "employee_app.gauth.validate_coordinates"
    }
}


