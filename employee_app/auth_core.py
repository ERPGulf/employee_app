"""Shared checks for the employee app's sign-in endpoints.

Every pre-login endpoint proves who the employee is with these helpers: exact
mobile lookup, OTPs, password checks with lockout, and token issue. Never log or
return OTPs, passwords, tokens or mobile numbers.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets

import frappe
import phonenumbers
from frappe.utils import cint
from frappe.utils.password import check_password, get_encryption_key
from werkzeug.wrappers import Response

OTP_TTL = 300  # seconds an OTP stays valid
OTP_TRIES = 5  # wrong codes that destroy an OTP
LOCK_AFTER = 10  # wrong OTPs or passwords in an hour that lock the employee
LOCK_FOR = 15 * 60  # seconds the lock lasts
TOO_MANY = "Too many attempts. Try again later."
PRIVILEGED_ROLES = {"Administrator", "System Manager"}

# What the app's shared service token may call. Each method proves the employee itself.
PRE_LOGIN_METHODS = {
    "employee_app.authentication.master_token",
    "employee_app.authentication.get_employee_login_policy",
    "employee_app.authentication.generate_and_send_otp",
    "employee_app.authentication.sign_up_api",
    "employee_app.authentication.otp_generate_for_cold_boot",
    "employee_app.authentication.cold_boot_api",
    "employee_app.authentication.refresh_employee_token",
    "employee_app.sign_in.otp_generate_for_sign_in",
    "employee_app.sign_in.sign_in_api",
    "employee_app.gauth.create_new_password",
    "employee_app.gauth.create_refresh_token",
}


# ── Replies ──────────────────────────────────────────────────────────────────

def json_reply(body, status):
    return Response(json.dumps(body), status=status, mimetype="application/json")


def throttled_reply():
    return json_reply({"status": "error", "message": TOO_MANY}, 429)


def log_failure(where):
    """Undo the failed request's writes, log its traceback without local
    variables, and return a reference the caller can quote."""
    frappe.db.rollback()
    ref = frappe.generate_hash(length=10)
    frappe.log_error(f"{where} failed [{ref}]", frappe.get_traceback(), defer_insert=True)
    return ref


def failure_reply(where):
    return json_reply({"status": "error", "message": "Something went wrong", "ref": log_failure(where)}, 500)


def auth_event(event, employee=None, **fields):
    """One line in the employee_app.auth log. Never pass OTPs, passwords,
    tokens, mobile numbers or provider replies."""
    logger = frappe.logger("employee_app.auth")
    logger.setLevel(logging.INFO)  # Frappe's production default, ERROR, would drop these
    logger.info({"event": event, "employee": employee, "ip": getattr(frappe.local, "request_ip", None), **fields})


# ── Who is calling: exact numbers only ───────────────────────────────────────

_EMPLOYEE_FIELDS = (
    "name, employee_name, cell_number, user_id, status, custom_authentication, custom_high_security,"
    " custom_user_created_password, custom_employee_has_signed_up"
)


def _region():
    country = frappe.db.get_single_value("System Settings", "country")
    code = country and frappe.db.get_value("Country", country, "code")
    return code.upper() if code else "SA"  # the app's home market, which WhatsApp delivery also assumes


def canonical_mobile(raw, region):
    """E.164 when the number parses, else its bare digits. Only the same number compares equal."""
    raw = str(raw or "").strip()
    try:
        number = phonenumbers.parse(raw, region)
        if phonenumbers.is_possible_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return re.sub(r"\D", "", raw) or None


def find_employee(raw_mobile):
    """The one Active employee with exactly this number, or None when unknown or ambiguous."""
    region = _region()
    wanted = canonical_mobile(raw_mobile, region)
    if not wanted:
        return None
    # Narrow by the last 7 digits, then compare whole numbers.
    # ponytail: unindexed scan, like the suffix match it replaces; add an indexed E.164 column if employees reach ~100k.
    rows = frappe.db.sql(
        f"""select {_EMPLOYEE_FIELDS} from `tabEmployee`
        where status = 'Active' and regexp_replace(cell_number, '[^0-9]', '') like %s""",
        ("%" + re.sub(r"\D", "", wanted)[-7:],),
        as_dict=True,
    )
    matches = [row for row in rows if canonical_mobile(row.cell_number, region) == wanted]
    if len(matches) > 1:
        auth_event("ambiguous_mobile", employees=[row.name for row in matches])
    return matches[0] if len(matches) == 1 else None


# ── Throttling: atomic fixed-window counters ─────────────────────────────────

# INCR, and start the window on the first hit, as one atomic step.
_HIT = "local n = redis.call('INCR', KEYS[1]) if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end return n"
# Delete the OTP only while it still holds this digest, so one code works once.
# Digests are keyed hashes, so comparison timing reveals nothing about the code.
_CONSUME = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


def _key(name):
    return frappe.cache().make_key(f"employee_app:auth:{name}")  # prefixed per site


def _hit(bucket, window):
    """Count one event in a fixed window and return the count so far."""
    return frappe.cache().eval(_HIT, 1, _key(bucket), window)


def throttle(bucket, limit, window):
    if _hit(bucket, window) > limit:
        raise frappe.RateLimitExceededError(TOO_MANY)


def throttle_ip(endpoint):
    """Coarse per-IP guard on a pre-login endpoint. Offices share one address, so it is generous."""
    limit = cint(frappe.conf.get("employee_app_ip_limit_per_hour")) or 600
    throttle(f"ip:{endpoint}:{getattr(frappe.local, 'request_ip', None)}", limit, 60 * 60)


def _check_lock(employee):
    # Raw get: RedisWrapper.exists() would prefix the already prefixed key again.
    if frappe.cache().get(_key(f"lock:{employee}")):
        raise frappe.RateLimitExceededError(TOO_MANY)


def _failed(employee):
    """Count a wrong OTP or password. LOCK_AFTER in an hour lock the employee for LOCK_FOR."""
    if _hit(f"fail:{employee}", 60 * 60) >= LOCK_AFTER:
        frappe.cache().set(_key(f"lock:{employee}"), 1, ex=LOCK_FOR)
        auth_event("employee_locked", employee)
    else:
        auth_event("auth_failed", employee)


# ── OTPs: random, stored as a keyed hash, single use, limited tries ──────────

def _digest(code):
    # Derived from the site's encryption key, which lives in site_config.json, not the database.
    key = hmac.new(get_encryption_key().encode(), b"employee_app.otp", hashlib.sha256).digest()
    return hmac.new(key, str(code).strip().encode(), hashlib.sha256).hexdigest()


def _test_otp():
    """A fixed OTP for automated testing: developer-mode sites only, set in site_config.json."""
    if frappe.conf.get("developer_mode") and frappe.conf.get("employee_app_test_otp"):
        return str(frappe.conf.get("employee_app_test_otp"))
    return None


def issue_otp(employee):
    """A fresh OTP for this employee, replacing any earlier one. Deliver it out of band only."""
    _check_lock(employee)
    throttle(f"otp-send:{employee}", 1, 60)
    throttle(f"otp-send-hour:{employee}", 5, 60 * 60)
    code = _test_otp() or str(100000 + secrets.randbelow(900000))  # 6 digits, no leading zero
    cache = frappe.cache()
    cache.set(_key(f"otp:{employee}"), _digest(code), ex=OTP_TTL)
    cache.delete(_key(f"otp-try:{employee}"))
    return code


def verify_otp(employee, code):
    """True once, for the right code. Wrong codes count towards OTP_TRIES and the lock."""
    _check_lock(employee)
    cache = frappe.cache()
    if code and cache.eval(_CONSUME, 1, _key(f"otp:{employee}"), _digest(code)) == 1:
        return True
    _failed(employee)
    if _hit(f"otp-try:{employee}", OTP_TTL) >= OTP_TRIES:
        cache.delete(_key(f"otp:{employee}"))
    return False


def send_otp(employee):
    """Issue an OTP to an employee row from find_employee and send it by WhatsApp.
    True when the provider accepted it."""
    code = issue_otp(employee.name)
    if _test_otp():
        return True
    result = frappe.call(
        "whatsapp_saudi.overrides.whtatsapp_notification.send_otp",
        phone=_clean_phone_number(employee.cell_number),
        otp_code=code,
    )
    # whatsapp_saudi answers {"success": True} or {"status": "success"}, depending on the provider.
    sent = isinstance(result, dict) and (result.get("success") is True or result.get("status") == "success")
    auth_event("otp_sent" if sent else "otp_not_delivered", employee.name)
    return sent


def _clean_phone_number(number):
    """The digits-only form WhatsApp delivery has always used."""
    phone = number.replace("+", "").replace("-", "").replace(" ", "")
    if phone.startswith("00"):
        phone = phone[2:]
    elif phone.startswith("0"):
        if len(phone) == 10:
            phone = "966" + phone[1:]
    else:
        if len(phone) < 10:
            phone = "966" + phone
    if phone.startswith("0"):
        phone = phone[1:]
    return phone


# ── Passwords ────────────────────────────────────────────────────────────────

def verify_password(employee, user, password):
    """check_password behind the same lock and failure count as OTPs. The app's
    managed placeholder is never a credential: those values were kept in plaintext."""
    from employee_app.authentication import is_placeholder_password

    _check_lock(employee)
    if not password or is_placeholder_password(password):
        return False
    try:
        check_password(user, password)
        return True
    except frappe.AuthenticationError:
        _failed(employee)
        return False


def password_too_weak(user, password):
    """Frappe's password policy (System Settings > Enable Password Policy). Passes while it is off."""
    from frappe.core.doctype.user.user import test_password_strength

    user_data = frappe.db.get_value("User", user, ["first_name", "middle_name", "last_name", "email", "birth_date"])
    result = test_password_strength(password, user_data=user_data)
    return bool(result) and not result["feedback"]["password_policy_validation_passed"]


def password_setup_allowed(emp):
    """The one rule for OTP-verified password setup.

    get_employee_login_policy reports it to the app as otp_verified_password_setup,
    and create_new_password checks it again when it changes the password.
    """
    from employee_app.authentication import AUTH_BOTH, get_login_policies

    user = emp.get("user_id")
    policies = get_login_policies(emp)
    return bool(
        # get_singles_dict, unlike get_single_value, doesn't throw before migrate adds the field.
        cint(frappe.db.get_singles_dict("Checkin App Setting").get("allow_in_app_password_setup"))
        and emp.get("status") == "Active"
        and emp.get("custom_employee_has_signed_up")
        and user
        and frappe.db.get_value("User", user, "enabled")
        and policies["sign_in_policy"]["password_policy"] != "No"
        # Both mode keeps two factors: an OTP may create the first password, never replace one.
        and not (policies["authentication"] == AUTH_BOTH and emp.get("custom_user_created_password"))
        and not PRIVILEGED_ROLES & set(frappe.get_roles(user))
        and not _testing_mode()
    )


def _testing_mode():
    return frappe.db.exists("DocType", "Whatsapp Saudi") and cint(
        frappe.db.get_single_value("Whatsapp Saudi", "testing")
    )


# ── Tokens: issued after verification, revoked when security tightens ────────

def issue_app_tokens(user):
    """An access and refresh token for the app's OAuth client, once the caller has
    proved who they are. None when the user is disabled."""
    from employee_app.gauth import _issue_bearer_token

    if not frappe.db.get_value("User", user, "enabled"):
        return None
    # ponytail: the first OAuth Client, as sign-in has always used; pin it to Checkin App Setting.app_key if a site has several.
    client = frappe.db.get_value("OAuth Client", {}, ["name", "scopes"], as_dict=True)
    if not client:
        frappe.throw("No OAuth Client found")
    return _issue_bearer_token(user, client.name, client.scopes)


def revoke_tokens(user):
    """End every OAuth session of this user: their access and refresh tokens stop working."""
    frappe.db.set_value("OAuth Bearer Token", {"user": user, "status": "Active"}, "status", "Revoked")


def rotate_refresh_token(refresh_token):
    """A new token pair for a refresh token, at most once per token, else None.

    A refresh token that comes back after use was probably copied, so it ends
    every session of its user (RFC 9700). A client retrying after a lost reply
    signs in again.
    """
    from employee_app.gauth import _issue_bearer_token

    name = refresh_token and frappe.db.get_value("OAuth Bearer Token", {"refresh_token": refresh_token}, "name")
    if not name:
        return None
    # Lock by primary key (refresh_token has no index): two requests can't both rotate one token.
    old = frappe.db.get_value(
        "OAuth Bearer Token", name, ["client", "user", "scopes", "status"], as_dict=True, for_update=True
    )
    if old.status != "Active":
        revoke_tokens(old.user)
        frappe.db.commit()  # nosemgrep: refresh callers may use GET, which Frappe rolls back
        auth_event("refresh_token_reused", user=old.user)
        return None
    if not frappe.db.get_value("User", old.user, "enabled"):
        return None
    frappe.db.set_value("OAuth Bearer Token", name, "status", "Revoked")
    return _issue_bearer_token(old.user, old.client, old.scopes)  # commits


def on_employee_security_change(doc, method=None):
    """Employee on_update: turning High Security on, or the employee leaving Active,
    ends their app sessions. Raw SQL updates skip this hook."""
    if not doc.get("user_id"):
        return
    tightened = doc.get("custom_high_security") and doc.has_value_changed("custom_high_security")
    inactive = doc.get("status") != "Active" and doc.has_value_changed("status")
    if tightened or inactive:
        revoke_tokens(doc.user_id)
        auth_event("tokens_revoked", doc.name, reason="high_security_on" if tightened else "not_active")


# ── The shared service token stays on the pre-login methods ──────────────────

def service_gate():
    """auth_hooks: limit the app's service token to PRE_LOGIN_METHODS.

    With employee_app_service_gate = "enforce" in site_config.json, other calls
    get 403. Otherwise they are only logged, so a tenant can review its app
    traffic before enforcing.
    """
    if not frappe.get_request_header("Authorization") or frappe.session.user in (None, "", "Guest"):
        return
    if frappe.session.user != frappe.db.get_single_value("Checkin App Setting", "user"):
        return
    path = frappe.request.path
    method = frappe.form_dict.get("cmd") or path.partition("/method/")[2] or path
    if method in PRE_LOGIN_METHODS:
        return
    auth_event("service_token_outside_pre_login", method=method)
    if frappe.conf.get("employee_app_service_gate") == "enforce":
        raise frappe.PermissionError
