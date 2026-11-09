import json
import os

import frappe
from frappe.utils import now
from frappe.utils.password import check_password, remove_encrypted_password


def execute():
    """Clear the plaintext copies in Employee.custom_employee_password and drop the field.

    First records, by user id only, which accounts still log in with a stored
    value: private/employee_app_exposed_passwords.json, for the incident
    follow-up. Only with employee_app_clear_exposed_placeholders set in
    site_config.json (an approved step) does it also remove the login password
    of accounts still on the app's exposed placeholder; nobody knows those, and
    OTP sign-in and in-app setup don't need them.

    The column stays until `bench trim-tables`, so the previous release can
    still run after a rollback.
    """
    from employee_app.auth_core import auth_event
    from employee_app.authentication import is_placeholder_password

    if frappe.db.has_column("Employee", "custom_employee_password"):
        rows = frappe.db.sql(
            """select user_id, custom_employee_password as stored from `tabEmployee`
            where ifnull(custom_employee_password, '') != ''""",
            as_dict=True,
        )
        exposed = {"placeholder": [], "chosen": []}
        for row in rows:
            if row.user_id and _still_current(row.user_id, row.stored):
                exposed["placeholder" if is_placeholder_password(row.stored) else "chosen"].append(row.user_id)

        path = frappe.get_site_path("private", "employee_app_exposed_passwords.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"recorded": now(), **exposed}, f, indent=1)

        cleared_placeholders = 0
        if frappe.conf.get("employee_app_clear_exposed_placeholders"):
            for user in exposed["placeholder"]:
                remove_encrypted_password("User", user)
            cleared_placeholders = len(exposed["placeholder"])

        frappe.db.sql("update `tabEmployee` set custom_employee_password = NULL")
        summary = {
            "plaintext_values_cleared": len(rows),
            "still_current_placeholder": len(exposed["placeholder"]),
            "still_current_chosen": len(exposed["chosen"]),
            "placeholder_passwords_removed": cleared_placeholders,
        }
        print(f"purge_plaintext_passwords: {summary}")
        auth_event("plaintext_passwords_cleared", **summary)

    frappe.delete_doc_if_exists("Custom Field", "Employee-custom_employee_password")


def _still_current(user, stored):
    try:
        check_password(user, stored, delete_tracker_cache=False)
        return True
    except frappe.AuthenticationError:
        return False
