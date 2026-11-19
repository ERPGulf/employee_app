# Copyright (c) 2026, ERPGulf.com
"""Push approval for ERPNext two-factor sign-in ("tap Allow on your phone"): the logic.

The HTTP endpoints are in api.py. Contract: developer guide > Frappe app tab.
Endpoints there:

Login page (guest, proven by Frappe's 2FA ticket, tmp_id):
    login_start     create the waiting request and send the push
    login_status    poll; signs the browser in once the phone approved

Mobile app (guest, proven by an Ed25519 signature, except register_device):
    register_device   enrol a phone, proven by a current 6-digit code
    pending           is a sign-in waiting for this user?
    respond           allow or deny one request
    update_push_token the Firebase token changed
    unregister        the user removed the account from the app

Support (here):
    bench --site <site> execute employee_app.TwoFA.push.check_setup

Never logged or returned: codes, OTP secrets, tmp_id, push tokens, signatures.
"""

import base64
import hashlib
import hmac
import json
import time

import frappe
import frappe.twofactor as twofactor
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from frappe.utils import cint, now_datetime
from frappe.utils.password import get_encryption_key

from employee_app.auth_core import (
    _key,
    auth_event,
    failure_reply,
    json_reply,
    throttled_reply,
)

DEVICE = "Authenticator Device"
REQUEST_TTL = 60  # seconds a sign-in request waits for the phone
WINDOW_TTL = 30 * 60  # seconds the registration window stays open after a correct password
MAX_SKEW = 90  # seconds between phone and server clocks
PUSH_LIMIT = (5, 10 * 60)  # push requests per user per 10 minutes
REG_FAIL_LIMIT = (5, 60 * 60)  # failed registrations per user per hour
POLL_LIMIT_PER_HOUR = 3600  # login_status calls per IP per hour (one every 2 s from many tabs)

SENDER = "whatsapp_saudi.whatsapp_saudi.doctype.whatsapp_saudi.whatsapp_saudi.send_firebase_notification"
FRAPPE_TICKET_SUFFIXES = ("_usr", "_pwd", "_otp_secret", "_token")


# ── Replies ──────────────────────────────────────────────────────────────────

def _ok(**fields):
    return json_reply({"status": "ok", **fields}, 200)


def _err(http, code, message, **fields):
    return json_reply({"status": "error", "code": code, "message": message, **fields}, http)


def _bad_request():
    return _err(400, "bad_request", "A field is missing or malformed")


def _guard(where, fn):
    """Run an endpoint body with the standard rate-limit and failure replies."""
    try:
        return fn()
    except frappe.RateLimitExceededError:
        return throttled_reply()
    except Exception:
        return failure_reply(f"twofa.api.{where}")


def _args():
    return frappe.form_dict


# ── Cache: plain strings under employee_app:auth:2fa:* ───────────────────────

def _cache():
    return frappe.cache()


def _get(name):
    raw = _cache().get(_key(name))
    return raw.decode() if isinstance(raw, bytes) else raw


def _set(name, value, ttl):
    _cache().set(_key(name), value, ex=int(ttl))


def _ttl(name):
    left = _cache().ttl(_key(name))
    return max(int(left or 0), 0)


def _del(*names):
    if names:
        _cache().delete(*[_key(n) for n in names])


def _ticket_name(tmp_id):
    return "2fa:ticket:" + hashlib.sha256(tmp_id.encode()).hexdigest()


def _load_request(request_id):
    raw = _get(f"2fa:req:{request_id}") if request_id else None
    return json.loads(raw) if raw else None


def _save_request(request_id, req, ttl=None):
    ttl = ttl if ttl is not None else _ttl(f"2fa:req:{request_id}")
    if ttl > 0:
        _set(f"2fa:req:{request_id}", json.dumps(req), ttl)


def _drop_request(request_id, req, tmp_id=None):
    names = [f"2fa:req:{request_id}"]
    if req and req.get("user") and _get(f"2fa:user:{req['user']}") == request_id:
        names.append(f"2fa:user:{req['user']}")
    if tmp_id:
        names.append(_ticket_name(tmp_id))
    _del(*names)


# ── Frappe's 2FA ticket (set by frappe.twofactor.cache_2fa_data) ─────────────

def _ticket_user(tmp_id):
    return frappe.cache.get_value(tmp_id + "_usr", use_local_cache=False)


def _clear_frappe_ticket(tmp_id):
    for suffix in FRAPPE_TICKET_SUFFIXES:
        frappe.cache.delete_value(tmp_id + suffix)


# ── OTP secret and its fingerprint ───────────────────────────────────────────

def _current_secret(user):
    """The user's OTP secret, or None. Never creates one."""
    if not twofactor.get_default(user + "_otpsecret"):
        return None
    return twofactor.get_otpsecret_for_(user)


def _fingerprint(secret):
    key = hmac.new(get_encryption_key().encode(), b"employee_app.TwoFA.push", hashlib.sha256).digest()
    return hmac.new(key, secret.encode(), hashlib.sha256).hexdigest()


def _two_factor_applies(user):
    from employee_app.TwoFA.policy import _policy_requires

    if _policy_requires(user):
        return True
    return bool(cint(frappe.get_system_settings("enable_two_factor_auth"))) and bool(
        twofactor.two_factor_is_enabled_for_(user)
    )


# ── Devices ──────────────────────────────────────────────────────────────────

def _valid_device(user):
    """The user's device record, or None. A record whose secret fingerprint no longer
    matches (an admin pressed Reset OTP Secret) is deleted on sight."""
    if not user or not frappe.db.exists(DEVICE, user):
        return None
    dev = frappe.db.get_value(
        DEVICE, user, ["name", "device_id", "public_key", "push_token", "secret_fingerprint"], as_dict=True
    )
    secret = _current_secret(user)
    if not secret or not hmac.compare_digest(dev.secret_fingerprint or "", _fingerprint(secret)):
        frappe.delete_doc(DEVICE, user, ignore_permissions=True, force=True)
        auth_event("2fa_device_removed", user=user, reason="secret_reset")
        return None
    return dev


def _verify_signed(endpoint, fields):
    """Check a signed mobile call. Returns (device, None) or (None, error reply)."""
    a = _args()
    user, device_id, sig = a.get("user"), a.get("device_id"), a.get("sig")
    ts = a.get("ts")
    values = [a.get(f) for f in fields]
    if not (user and device_id and sig and str(ts or "").lstrip("-").isdigit()) or any(v in (None, "") for v in values):
        return None, _bad_request()

    dev = _valid_device(user)
    if not dev:
        return None, _err(410, "device_removed", "This account was reset. Scan the new QR code")
    if not hmac.compare_digest(dev.device_id, str(device_id)):
        auth_event("2fa_bad_signature", user=user, endpoint=endpoint)
        return None, _err(401, "bad_signature", "Signature check failed")

    now = int(time.time())
    if abs(now - int(ts)) > MAX_SKEW:
        return None, _err(401, "clock_skew", "Set your phone's time to automatic", server_time=now)

    message = "\n".join([endpoint, user, device_id, str(ts)] + [str(v) for v in values]).encode()
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(dev.public_key)).verify(base64.b64decode(sig), message)
    except (InvalidSignature, ValueError, TypeError):
        auth_event("2fa_bad_signature", user=user, endpoint=endpoint)
        return None, _err(401, "bad_signature", "Signature check failed")

    frappe.db.set_value(DEVICE, user, "last_used_on", now_datetime(), update_modified=False)
    return dev, None


# ── Push ─────────────────────────────────────────────────────────────────────

def _site_label():
    return frappe.get_system_settings("otp_issuer_name") or frappe.local.site


def _browser_label(ua):
    ua = ua or ""
    browser = next(
        (name for pat, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                ("Chrome/", "Chrome"), ("Safari/", "Safari")) if pat in ua),
        "Browser",
    )
    system = next(
        (name for pat, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                                ("iPad", "iPad"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if pat in ua),
        "",
    )
    return f"{browser} on {system}" if system else browser


def _send_push(request_id, token, site, user):
    """Background job: send the notification through whatsapp_saudi, record the result."""
    sent = False
    try:
        result = frappe.call(SENDER, title="Login Attempt", body=f"Log in to {site} as {user}", client_token=token)
        sent = isinstance(result, dict) and bool(result.get("response")) and "error" not in result
    except Exception:
        sent = False
    req = _load_request(request_id)
    if req:
        req["push"] = "sent" if sent else "failed"
        _save_request(request_id, req)


def _firebase_on():
    try:
        return "whatsapp_saudi" in frappe.get_installed_apps() and bool(
            cint(frappe.db.get_single_value("Whatsapp Saudi", "firebase_notification"))
        )
    except Exception:
        return False


# ── Support ──────────────────────────────────────────────────────────────────

def check_setup():
    """Print pass or fail for each setting push approval needs on this site."""
    from urllib.parse import urlparse

    def line(ok, text):
        print(("PASS  " if ok else "FAIL  ") + text)

    enabled = cint(frappe.get_system_settings("enable_two_factor_auth"))
    method = frappe.get_system_settings("two_factor_method")
    line(enabled and method == "OTP App", f"Two-factor on with method OTP App (now: {'on' if enabled else 'off'}, {method})")

    from employee_app.TwoFA import policy as twofa

    roles = frappe.get_all("Role", filters={"two_factor_auth": 1}, pluck="name")
    line(bool(roles) or twofa.get_policy() != twofa.POLICY_STANDARD,
         f"Who must use it: policy {twofa.get_policy()}; roles with 2FA ticked: {', '.join(roles) or 'none'}")

    issuer = frappe.get_system_settings("otp_issuer_name") or ""
    url = urlparse(frappe.utils.get_url())
    host = url.hostname + (f":{url.port}" if url.port else "")
    line(issuer.replace("_", ":") == host, f"OTP Issuer Name '{issuer}' matches the site address '{host}'")

    outgoing = frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1})
    line(bool(outgoing), "Default outgoing Email Account")

    line(_firebase_on(), "Firebase Notification on in Whatsapp Saudi settings")

    from frappe.utils.scheduler import is_scheduler_inactive

    line(not is_scheduler_inactive(), "Scheduler and background workers active")
