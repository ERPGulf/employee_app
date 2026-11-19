# Copyright (c) 2026, ERPGulf.com
"""Two-Factor Policy: who must use two-factor sign-in, whatever the screen says.

Read from site_config.json, so only the ERPGulf backend team can change it.
"""

import frappe
from frappe import _
from frappe.utils import cint

APP = "employee_app"

# Two-Factor Policy. Locked: it lives in site_config.json, not in System Settings,
# so only the ERPGulf backend team can change it:
#   bench --site <site> set-config employee_app_twofa_policy "Maximum: all users"
# Missing or unknown value = High.
POLICY_CONFIG_KEY = "employee_app_twofa_policy"
POLICY_MAXIMUM = "Maximum: all users"
POLICY_HIGH = "High: all system users"
POLICY_STANDARD = "Standard: by role"
POLICIES = (POLICY_MAXIMUM, POLICY_HIGH, POLICY_STANDARD)


def get_policy() -> str:
	policy = frappe.conf.get(POLICY_CONFIG_KEY)
	return policy if policy in POLICIES else POLICY_HIGH


@frappe.whitelist()
def policy_info() -> str:
	"""For the note on the System Settings form (public/js/2fa/system_settings.js)."""
	frappe.only_for("System Manager")
	return get_policy()


# Never use 2FA. Administrator gets a long random password that nobody keeps;
# when it is needed, the backend team resets it with bench set-admin-password.
EXEMPT_USERS = ("Administrator",)


def is_exempt(user) -> bool:
	if APP not in frappe.get_installed_apps():
		return False
	name = user if isinstance(user, str) else getattr(user, "name", None)
	return name in EXEMPT_USERS


def _policy_requires(user) -> bool:
	"""True when the policy makes two-factor sign-in compulsory for this user,
	whatever their roles, the restricted-IP bypass or the Enable Two Factor Auth
	tick say."""
	if APP not in frappe.get_installed_apps():
		return False
	name = user if isinstance(user, str) else getattr(user, "name", None)
	if not name or name == "Guest":
		return False

	policy = get_policy()
	if policy == POLICY_MAXIMUM:
		return True
	if policy == POLICY_HIGH:
		return frappe.db.get_value("User", name, "user_type") == "System User"
	return False


def validate_system_settings(doc, method=None):
	"""doc_events > System Settings > validate. Under High or Maximum, two-factor
	sign-in stays switched on, so the screen never shows it as off."""
	if get_policy() != POLICY_STANDARD and not cint(doc.enable_two_factor_auth):
		doc.enable_two_factor_auth = 1
		frappe.msgprint(
			_("Two-factor sign-in is required by your security policy and stays on. Contact ERPGulf support to change the policy."),
			alert=True,
		)
