# Copyright (c) 2026, ERPGulf.com
"""Web sign-in: on-screen QR enrolment, plus the hooks that apply the policy (policy.py).

Rules
- Only an admin action opens the window: creating a user, or Reset OTP Secret
  on another user's form. Never a self password change, Forgot password,
  self sign-up or a user resetting their own secret.
- The QR code is shown only to users who are not enrolled yet.
- The window closes after WINDOW_MINUTES, or as soon as the user enrols.
- After it expires, the user is told to ask their administrator for a new
  QR code (Reset OTP Secret). No QR link is emailed. Users who never had a
  window keep Frappe's standard behaviour (QR link by email).
- The QR code is returned only inside the login response, after the
  password check has passed.

Frappe core is not edited. One function, frappe.twofactor.get_verification_obj,
is wrapped at runtime from the before_login hook. The wrapper hands every
case it does not own back to the original, and does nothing on sites where
employee_app is not installed (the wrap lives in the worker process, which can
serve several sites).

State is kept beside Frappe's own 2FA state, in the "__2fa" defaults:
    <user>_otplogin          set by Frappe when the user has enrolled
    <user>_qr_window_until   end of the on-screen window (ISO datetime)
"""

import pyotp

import frappe
import frappe.twofactor as twofactor
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime, time_diff_in_seconds

from employee_app.TwoFA.policy import APP, _policy_requires

WINDOW_MINUTES = 60
WINDOW_KEY = "_qr_window_until"
# Frappe keeps a 2FA login session (tmp_id) for 180 seconds for the OTP App method.
LOGIN_SESSION_SECONDS = 180


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------


def open_window(user: str) -> None:
	until = add_to_date(now_datetime(), minutes=WINDOW_MINUTES)
	twofactor.set_default(user + WINDOW_KEY, until.isoformat())


def close_window(user: str) -> None:
	twofactor.clear_default(user + WINDOW_KEY)


def seconds_left(user: str) -> int:
	until = twofactor.get_default(user + WINDOW_KEY)
	if not until:
		return 0
	left = int(time_diff_in_seconds(get_datetime(until), now_datetime()))
	return max(left, 0)


def is_enrolled(user: str) -> bool:
	return bool(twofactor.get_default(user + "_otplogin"))


# --------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------


def on_user_after_insert(doc, method=None):
	"""doc_events > User > after_insert. Opens the window for users an admin creates."""
	if frappe.session.user in ("Guest", doc.name):
		return  # self sign-up
	open_window(doc.name)


@frappe.whitelist()
def reset_otp_secret(user: str):
	"""Replaces frappe.twofactor.reset_otp_secret (override_whitelisted_methods).

	Runs the core reset, with its own permission check and email, then opens
	the window when an admin reset someone else's secret.
	"""
	twofactor.reset_otp_secret(user)
	if frappe.session.user != user:
		open_window(user)
		frappe.msgprint(
			_("For the next {0} minutes, the user can scan the QR code on the sign-in page.").format(
				WINDOW_MINUTES
			)
		)


def on_login(login_manager=None):
	"""on_login hook. Closes the window once the user has enrolled."""
	user = getattr(login_manager, "user", None)
	if user and twofactor.get_default(user + WINDOW_KEY) and is_enrolled(user):
		close_window(user)


def install(login_manager=None):
	"""before_login hook. Wraps three frappe.twofactor functions, once per worker process.

	get_verification_obj        on-screen QR enrolment
	two_factor_is_enabled       Two-Factor Policy, also over the restricted-IP bypass
	two_factor_is_enabled_for_  Two-Factor Policy in the code check, so a policy user
	                            can never finish signing in without a code
	"""
	_wrap(
		"get_verification_obj",
		lambda original: lambda user, token, otp_secret: _verification_obj(original, user, token, otp_secret),
	)
	_wrap(
		"two_factor_is_enabled",
		lambda original: lambda user=None: True if (user and _policy_requires(user)) else original(user),
	)
	_wrap(
		"two_factor_is_enabled_for_",
		lambda original: lambda user: True if _policy_requires(user) else original(user),
	)


def _wrap(name, make):
	current = getattr(twofactor, name)
	if getattr(current, "_employee_app", False):
		return
	wrapper = make(current)
	wrapper._employee_app = True
	setattr(twofactor, name, wrapper)


# --------------------------------------------------------------------------
# Verification object
# --------------------------------------------------------------------------


def _verification_obj(original, user, token, otp_secret):
	if APP not in frappe.get_installed_apps():
		return original(user, token, otp_secret)
	if twofactor.get_verification_method() != "OTP App" or is_enrolled(user):
		return original(user, token, otp_secret)

	if not twofactor.get_default(user + WINDOW_KEY):
		return original(user, token, otp_secret)  # no window was ever opened: standard flow

	left = seconds_left(user)
	if not left:
		# Expired: no QR code and no email. The admin issues a new one with
		# Reset OTP Secret, which opens a fresh window.
		return {"method": "OTP App", "setup": False, "qrcode": {"expired": True}}

	issuer = frappe.get_system_settings("otp_issuer_name")
	totp_uri = pyotp.TOTP(otp_secret).provisioning_uri(user, issuer_name=issuer)
	svg = twofactor.get_qr_svg_code(totp_uri)

	# Core login.js passes "qrcode" to continue_otp_app(); public/js/2fa/login.js reads it.
	# "setup": False keeps core's own message if the script is missing.
	return {
		"method": "OTP App",
		"setup": False,
		"qrcode": {
			"svg": svg.decode() if isinstance(svg, bytes) else svg,
			"user": user,
			"seconds_left": left,
			"session_seconds": LOGIN_SESSION_SECONDS,
		},
	}
