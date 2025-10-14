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
]


doc_events = {
    "Employee": {
        "on_update": "employee_app.user_qa_code.create_qr_code",
        "on_trash": "employee_app.delete_qr_code_file"
    }
}

