"""Evidence and incident tooling for the auth remediation, one site at a time.

    bench --site <site> execute employee_app.auth_audit.run

Prints presence and counts only: never OTPs, passwords, tokens or mobile numbers.
"""

import hashlib
import json
from collections import Counter

import frappe
from frappe.utils.password import Auth


def run():
    from employee_app.auth_core import PRIVILEGED_ROLES, _region, canonical_mobile

    service_user = frappe.db.get_single_value("Checkin App Setting", "user")
    roles = set(frappe.get_roles(service_user)) - {"All", "Guest"} if service_user else set()
    whatsapp = frappe.db.exists("DocType", "Whatsapp Saudi")
    active =frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "cell_number", "user_id"])

    region = _region()
    numbers = Counter(canonical_mobile(e.cell_number, region) for e in active if e.cell_number)
    linked_users = [e.user_id for e in active if e.user_id]

    report = {
        "site": frappe.local.site,
        # Item 4: what the public service token can reach.
        "service_user_set": bool(service_user),
        "service_user_is_administrator": service_user == "Administrator",
        "service_user_roles": sorted(roles),
        "service_user_privileged": bool(PRIVILEGED_ROLES & roles),
        "service_user_can_read": {
            doctype: bool(service_user and frappe.has_permission(doctype, "read", user=service_user))
            for doctype in ("Employee", "User", "Error Log", "OAuth Bearer Token", "Checkin App Setting")
        },
        "service_user_active_tokens": frappe.db.count("OAuth Bearer Token", {"user": service_user, "status": "Active"})
        if service_user
        else 0,
        "service_gate_mode": frappe.conf.get("employee_app_service_gate") or "log",
        # Item 1: presence only.
        "whatsapp_testing_on": bool(whatsapp and frappe.db.get_single_value("Whatsapp Saudi", "testing")),
        "whatsapp_testing_otp_set": bool(whatsapp and frappe.db.get_single_value("Whatsapp Saudi", "testing_otp")),
        "developer_mode": bool(frappe.conf.get("developer_mode")),
        # Item 5: must be 0 (or "dropped") after the purge patch.
        "plaintext_password_values": frappe.db.sql(
            "select count(*) from `tabEmployee` where ifnull(custom_employee_password, '') != ''"
        )[0][0]
        if frappe.db.has_column("Employee", "custom_employee_password")
        else "dropped",
        # Item 8: exact matching refuses these employees until HR fixes the numbers.
        "active_employees": len(active),
        "active_without_mobile": sum(1 for e in active if not e.cell_number),
        "mobiles_shared_by_active_employees": sum(1 for count in numbers.values() if count > 1),
        "active_employees_on_shared_mobiles": sum(count for count in numbers.values() if count > 1),
        # Many of these mean a wrong System Settings country or bad data: exact matching may miss them.
        "region": region,
        "active_mobiles_not_valid_for_region": sum(1 for e in active if e.cell_number and not _valid(e.cell_number, region)),
        # Items 9 and 11.
        "password_setup_switch_on": bool(
            frappe.db.get_singles_dict("Checkin App Setting").get("allow_in_app_password_setup")
        ),
        "signed_up": frappe.db.count("Employee", {"custom_employee_has_signed_up": 1}),
        "signed_up_without_own_password": frappe.db.count(
            "Employee", {"custom_employee_has_signed_up": 1, "custom_user_created_password": 0}
        ),
        "active_employees_with_privileged_user": sum(
            1 for user in linked_users if PRIVILEGED_ROLES & set(frappe.get_roles(user))
        ),
        "active_employees_with_disabled_user": frappe.db.count("User", {"name": ["in", linked_users], "enabled": 0})
        if linked_users
        else 0,
        "inactive_employees_with_active_tokens": frappe.db.sql(
            """select count(distinct e.name) from `tabEmployee` e
            join `tabOAuth Bearer Token` t on t.user = e.user_id
            where t.status = 'Active' and e.status != 'Active'"""
        )[0][0],
    }
    print(frappe.as_json(report))
    return report


def _valid(raw, region):
    import phonenumbers

    try:
        return phonenumbers.is_valid_number(phonenumbers.parse(str(raw), region))
    except phonenumbers.NumberParseException:
        return False


def password_fingerprint(user):
    """SHA-256 of the user's current password hash: shows whether it changed, reveals nothing."""
    row = (
        frappe.qb.from_(Auth)
        .select(Auth.password)
        .where((Auth.doctype == "User") & (Auth.name == user) & (Auth.fieldname == "password"))
        .run()
    )
    return hashlib.sha256(row[0][0].encode()).hexdigest() if row else None


def remove_exposed_passwords(kind="placeholder", dry_run=True):
    """Approved incident step: remove the login password of accounts that the purge
    patch recorded as still using a plaintext-exposed value, if it hasn't changed since.

        bench --site <site> execute employee_app.auth_audit.remove_exposed_passwords \\
            --kwargs "{'kind': 'placeholder', 'dry_run': False}"

    "placeholder": the app's managed values; nobody knows them and mobile sign-in doesn't use them.
    "chosen": employees' own passwords; they then set a new one in the app or by Forgot Password.
    """
    from frappe.utils.password import remove_encrypted_password

    from employee_app.auth_core import auth_event

    with open(frappe.get_site_path("private", "employee_app_exposed_passwords.json")) as f:
        recorded = [a for a in json.load(f)["accounts"] if a["kind"] == kind]
    unchanged = [a["user"] for a in recorded if a["fingerprint"] and password_fingerprint(a["user"]) == a["fingerprint"]]
    if not dry_run:
        for user in unchanged:
            remove_encrypted_password("User", user)
        auth_event("exposed_passwords_removed", kind=kind, count=len(unchanged))
    report = {"kind": kind, "recorded": len(recorded), "unchanged_since": len(unchanged),
              "removed": 0 if dry_run else len(unchanged)}
    print(frappe.as_json(report))
    return report
