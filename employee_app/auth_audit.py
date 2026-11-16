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
    service_user_can_read = {}
    for doctype in ("Employee", "User", "Error Log", "OAuth Bearer Token", "Checkin App Setting"):
        allowed = False
        if service_user:
            allowed = frappe.has_permission(doctype, "read", user=service_user)
        service_user_can_read[doctype] = bool(allowed)

    report = {
        "site": frappe.local.site,
        # Item 4: what the public service token can reach.
        "service_user_set": bool(service_user),
        "service_user_is_administrator": service_user == "Administrator",
        "service_user_roles": sorted(roles),
        "service_user_privileged": bool(PRIVILEGED_ROLES & roles),
        "service_user_can_read": service_user_can_read,
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
        # The app cannot sign these in; see restore_signups_reset_by_policy_change.
        "active_not_signed_up_with_own_password": frappe.db.count(
            "Employee", {"status": "Active", "custom_employee_has_signed_up": 0, "custom_user_created_password": 1}
        ),
        "password_setup_pending": frappe.db.count("Employee", {"custom_password_setup_pending": 1})
        if frappe.db.has_column("Employee", "custom_password_setup_pending")
        else "not migrated",
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

    # Reviewed: bench-only tool; both path components are fixed, scoped to the initialized site.
    with open(frappe.get_site_path("private", "employee_app_exposed_passwords.json")) as f:  # nosemgrep: frappe-security-file-traversal
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


def restore_signups_reset_by_policy_change(dry_run=True):
    """Approved repair for sites that ran commit 23d3f1c, whose hook unticked "Employee has
    signed up" whenever Authentication changed. Using the Employee change history, it
    re-ticks the flag where that reset is still its latest change, and grants first-password
    setup where the current policy needs a password the employee has not set.

        bench --site <site> execute employee_app.auth_audit.restore_signups_reset_by_policy_change \\
            --kwargs "{'dry_run': False}"

    A deliberate untick made in the same save as an Authentication change looks the same
    and is restored too. Counts only.
    """
    from frappe.utils import cint

    from employee_app.auth_core import auth_event
    from employee_app.authentication import get_login_policies

    latest = {}  # employee -> the newest recorded change of the flag, with its siblings
    for version in frappe.get_all(
        "Version",
        filters={"ref_doctype": "Employee", "data": ["like", "%custom_employee_has_signed_up%"]},
        fields=["docname", "data"],
        order_by="creation asc",
    ):
        changed = {row[0]: row[1:] for row in json.loads(version.data).get("changed", [])}
        if "custom_employee_has_signed_up" in changed:
            latest[version.docname] = changed
    reset = [
        name
        for name, changed in latest.items()
        if [cint(v) for v in changed["custom_employee_has_signed_up"]] == [1, 0] and "custom_authentication" in changed
    ]

    can_grant = frappe.db.has_column("Employee", "custom_password_setup_pending")
    restored = granted = 0
    for name in reset:
        emp = frappe.db.get_value(
            "Employee",
            name,
            ["custom_employee_has_signed_up", "custom_authentication", "custom_user_created_password"],
            as_dict=True,
        )
        if not emp or emp.custom_employee_has_signed_up:
            continue  # deleted, or signed up again since
        values = {"custom_employee_has_signed_up": 1}
        if (
            can_grant
            and not emp.custom_user_created_password
            and get_login_policies(emp)["sign_in_policy"]["password_policy"] == "Mandatory"
        ):
            values["custom_password_setup_pending"] = 1
        restored += 1
        granted += len(values) - 1
        if not dry_run:
            frappe.db.set_value("Employee", name, values)

    if not dry_run:
        auth_event("signups_restored", count=restored, granted=granted)
    report = {"reset_by_policy_change": len(reset), "restored": restored, "first_password_granted": granted,
              "dry_run": bool(dry_run)}
    print(frappe.as_json(report))
    return report
