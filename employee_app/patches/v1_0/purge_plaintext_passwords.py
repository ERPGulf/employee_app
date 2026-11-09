import json
import os

import frappe
from frappe.utils import now
from frappe.utils.password import check_password


def execute():
    """Clear the plaintext copies in Employee.custom_employee_password and drop the field.

    First records which accounts still log in with a stored value: user id, kind
    (the app's placeholder or the employee's own) and a fingerprint of the current
    password hash, never the value. It goes to private/employee_app_exposed_passwords.json,
    which auth_audit.remove_exposed_passwords uses once removal is approved.

    The column stays until `bench trim-tables`, so the previous release can still
    run after a rollback.
    """
    from employee_app.auth_audit import password_fingerprint
    from employee_app.auth_core import auth_event
    from employee_app.authentication import is_placeholder_password

    if frappe.db.has_column("Employee", "custom_employee_password"):
        rows = frappe.db.sql(
            """select user_id, custom_employee_password as stored from `tabEmployee`
            where ifnull(custom_employee_password, '') != ''""",
            as_dict=True,
        )
        if rows:
            accounts = [
                {
                    "user": row.user_id,
                    "kind": "placeholder" if is_placeholder_password(row.stored) else "chosen",
                    "fingerprint": password_fingerprint(row.user_id),  # after the check, which may rehash
                }
                for row in rows
                if row.user_id and _still_current(row.user_id, row.stored)
            ]
            path = frappe.get_site_path("private", "employee_app_exposed_passwords.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"recorded": now(), "accounts": accounts}, f, indent=1)

            frappe.db.sql("update `tabEmployee` set custom_employee_password = NULL")
            summary = {
                "plaintext_values_cleared": len(rows),
                "still_current_placeholder": sum(a["kind"] == "placeholder" for a in accounts),
                "still_current_chosen": sum(a["kind"] == "chosen" for a in accounts),
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
