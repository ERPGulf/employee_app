# Copyright (c) 2026, ERPGulf.com
"""Push approval endpoints. URL: /api/method/employee_app.TwoFA.api.<endpoint>

Login page (guest, proven by Frappe's 2FA ticket, tmp_id): login_start, login_status
Mobile app (guest, proven by an Ed25519 signature): register_device (proven by a
6-digit code instead), pending, respond, update_push_token, unregister

The logic lives in push.py. Never logged or returned: codes, OTP secrets,
tmp_id, push tokens, signatures.
"""

import base64
import hmac
import json
import re
import secrets
import time

import frappe
import frappe.twofactor as twofactor
import pyotp
from frappe.utils import cint, now_datetime

from employee_app.auth_core import auth_event, throttle, throttle_ip, throttled_reply
from employee_app.TwoFA.push import (
    DEVICE,
    POLL_LIMIT_PER_HOUR,
    PUSH_LIMIT,
    REG_FAIL_LIMIT,
    REQUEST_TTL,
    WINDOW_TTL,
    _args,
    _bad_request,
    _browser_label,
    _clear_frappe_ticket,
    _current_secret,
    _del,
    _drop_request,
    _err,
    _fingerprint,
    _firebase_on,
    _get,
    _guard,
    _load_request,
    _ok,
    _save_request,
    _set,
    _site_label,
    _ticket_name,
    _ticket_user,
    _ttl,
    _two_factor_applies,
    _valid_device,
    _verify_signed,
)


# ── Login page ───────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["POST"])
def login_start(tmp_id=None, resend=0):
    def run():
        throttle_ip("twofa.login_start")
        if not tmp_id:
            return _bad_request()
        user = _ticket_user(tmp_id)
        if not user:
            return _ok(state="expired")

        # The only place the registration window opens: right after a correct password.
        _set(f"2fa:window:{user}", "1", WINDOW_TTL)

        dev = _valid_device(user)
        if not dev:
            return _ok(state="no_device")

        ticket = _ticket_name(tmp_id)
        existing_id = _get(ticket)
        existing = _load_request(existing_id)
        if existing and not cint(resend):
            return _ok(state=existing["status"], expires_in=_ttl(f"2fa:req:{existing_id}"), push=existing.get("push"))

        try:
            throttle(f"2fa:push:{user}", *PUSH_LIMIT)
        except frappe.RateLimitExceededError:
            return _ok(state="rate_limited")

        if existing:
            _drop_request(existing_id, existing)

        request_id = secrets.token_urlsafe(16)
        req = {
            "user": user,
            "tmp_id": tmp_id,
            "status": "pending",
            "ip": getattr(frappe.local, "request_ip", None),
            "browser": _browser_label(frappe.get_request_header("User-Agent")),
            "created": str(now_datetime())[:19],
            "push": "queued" if dev.push_token else "failed",
        }
        _set(f"2fa:req:{request_id}", json.dumps(req), REQUEST_TTL)
        _set(ticket, request_id, REQUEST_TTL)
        _set(f"2fa:user:{user}", request_id, REQUEST_TTL)

        if dev.push_token:
            frappe.enqueue(
                "employee_app.TwoFA.push._send_push",
                queue="short",
                enqueue_after_commit=True,
                request_id=request_id,
                token=dev.push_token,
                site=_site_label(),
                user=user,
            )
        auth_event("2fa_push_requested", user=user)
        return _ok(state="pending", expires_in=REQUEST_TTL, push=req["push"])

    return _guard("login_start", run)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login_status(tmp_id=None):
    def run():
        # The page polls every 2 seconds, so this gets its own, larger per-IP limit.
        throttle(f"ip:twofa.login_status:{getattr(frappe.local, 'request_ip', None)}", POLL_LIMIT_PER_HOUR, 3600)
        if not tmp_id:
            return _bad_request()
        ticket = _ticket_name(tmp_id)
        request_id = _get(ticket)
        req = _load_request(request_id)
        if not req:
            return _ok(state="expired")

        if req["status"] == "pending":
            return _ok(state="pending", expires_in=_ttl(f"2fa:req:{request_id}"), push=req.get("push"))

        if req["status"] == "denied":
            _drop_request(request_id, req, tmp_id)
            return _ok(state="denied")

        # approved: sign this browser in, once
        user = req["user"]
        ticket_user = _ticket_user(tmp_id)
        _drop_request(request_id, req, tmp_id)
        if not ticket_user or not hmac.compare_digest(str(ticket_user), str(user)):
            return _ok(state="expired")
        _clear_frappe_ticket(tmp_id)
        if not twofactor.get_default(user + "_otplogin"):
            twofactor.set_default(user + "_otplogin", 1)  # as Frappe does after a correct code
        frappe.local.login_manager.login_as(user)
        auth_event("2fa_push_login", user=user)
        return _ok(state="approved", home_page=frappe.local.response.get("home_page") or "/app")

    return _guard("login_status", run)


# ── Mobile app ───────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_device(user=None, code=None, device_id=None, public_key=None, push_token=None, platform=None, app_id=None):
    def run():
        throttle_ip("twofa.register_device")
        if not (user and code and device_id and public_key and platform in ("ios", "android")):
            return _bad_request()
        try:
            if len(base64.b64decode(public_key, validate=True)) != 32:
                return _bad_request()
        except (ValueError, TypeError):
            return _bad_request()
        if len(str(device_id)) > 140 or not re.fullmatch(r"\d{6}", str(code).strip()):
            return _bad_request()

        fail_bucket = f"2fa:regfail:{user}"
        if cint(_get(fail_bucket)) >= REG_FAIL_LIMIT[0]:
            return throttled_reply()

        def bad_code():
            count = cint(_get(fail_bucket)) + 1
            _set(fail_bucket, str(count), _ttl(fail_bucket) or REG_FAIL_LIMIT[1])
            auth_event("2fa_register_failed", user=user)
            return _err(401, "bad_code", "Could not register. Check the code and try again")

        if not _get(f"2fa:window:{user}"):
            return _err(403, "window_closed", "Sign in on the web first, then scan again")

        if not frappe.db.get_value("User", user, "enabled") or not _two_factor_applies(user):
            return bad_code()
        secret = _current_secret(user)
        if not secret or not pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1):
            return bad_code()

        dev = _valid_device(user)
        if dev and not hmac.compare_digest(dev.device_id, str(device_id)):
            return _err(409, "device_exists", "Another phone is registered. Ask your admin to reset")

        values = {
            "device_id": device_id,
            "public_key": public_key,
            "push_token": push_token or "",
            "platform": platform,
            "app_id": app_id or "",
            "secret_fingerprint": _fingerprint(secret),
            "registered_on": now_datetime(),
        }
        if dev:
            frappe.db.set_value(DEVICE, user, values)
        else:
            frappe.get_doc({"doctype": DEVICE, "user": user, **values}).insert(ignore_permissions=True)

        _del(f"2fa:window:{user}", fail_bucket)
        auth_event("2fa_device_registered", user=user, platform=platform)
        return _ok(push=_firebase_on(), server_time=int(time.time()))

    return _guard("register_device", run)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def pending(**kwargs):
    def run():
        throttle_ip("twofa.pending")
        dev, error = _verify_signed("pending", [])
        if error:
            return error
        user = _args().get("user")
        request_id = _get(f"2fa:user:{user}")
        req = _load_request(request_id)
        if not req or req.get("status") != "pending":
            return _ok(request=None)
        return _ok(
            request={
                "request_id": request_id,
                "site": _site_label(),
                "user": user,
                "ip": req.get("ip"),
                "browser": req.get("browser"),
                "created": req.get("created"),
                "expires_in": _ttl(f"2fa:req:{request_id}"),
            }
        )

    return _guard("pending", run)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def respond(**kwargs):
    def run():
        throttle_ip("twofa.respond")
        dev, error = _verify_signed("respond", ["request_id", "action"])
        if error:
            return error
        a = _args()
        user, request_id, action = a.get("user"), str(a.get("request_id")), a.get("action")
        if action not in ("allow", "deny"):
            return _bad_request()

        req = _load_request(request_id)
        if not req or req.get("status") != "pending" or not hmac.compare_digest(str(req.get("user")), str(user)):
            return _ok(result="expired")

        if action == "allow":
            req["status"] = "approved"
            _save_request(request_id, req)  # keeps the remaining lifetime
            result = "approved"
        else:
            req["status"] = "denied"
            _save_request(request_id, req)
            _clear_frappe_ticket(req["tmp_id"])  # a typed code now fails for this attempt
            result = "denied"

        if _get(f"2fa:user:{user}") == request_id:
            _del(f"2fa:user:{user}")
        auth_event("2fa_push_" + result, user=user)
        return _ok(result=result)

    return _guard("respond", run)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_push_token(**kwargs):
    def run():
        throttle_ip("twofa.update_push_token")
        dev, error = _verify_signed("update_push_token", ["push_token"])
        if error:
            return error
        frappe.db.set_value(DEVICE, dev.name, "push_token", _args().get("push_token"), update_modified=False)
        return _ok()

    return _guard("update_push_token", run)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def unregister(**kwargs):
    def run():
        throttle_ip("twofa.unregister")
        dev, error = _verify_signed("unregister", [])
        if error:
            return error
        frappe.delete_doc(DEVICE, dev.name, ignore_permissions=True, force=True)
        auth_event("2fa_device_unregistered", user=dev.name)
        return _ok()

    return _guard("unregister", run)
