import json

import frappe
from werkzeug.wrappers import Response

from employee_app.auth_core import (
    OTP_TTL,
    failure_reply,
    find_employee,
    issue_app_tokens,
    send_otp,
    throttle_ip,
    throttled_reply,
    verify_otp,
    verify_password,
)
from employee_app.authentication import (
    POLICY_NONE,
    _credentials_refused,
    get_login_policies,
    is_placeholder_password,
)


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Step 1 of sign-in / cold boot: check password and/or send OTP
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=True)
def otp_generate_for_sign_in(mobile_no=None, password=None, login_type="sign_in"):
    """
    Start sign-in (or cold-boot re-verification) for an existing employee,
    looked up by phone number.

    The policy comes from get_login_policies (Employee's Authentication and
    High Security fields) — "sign_in_policy" or "cold_boot_policy" depending
    on login_type.

    Params:
        mobile_no  : phone number used to look up the Employee.
        password   : required when the policy's password_policy is
                     "Mandatory" — validated against the login password of
                     the User linked via Employee.user_id. Ignored otherwise.
        login_type : "sign_in" (default) or "cold_boot".

    Result:
        - otp_policy "Mandatory" (OTP Authentication, Both): an OTP is sent
          and the client must finish with
          sign_in_api(mobile_no, otp, password, login_type).
        - otp_policy "No" (password only): the access + refresh token is
          issued immediately, in this same call.
        - Optional (password and OTP both "Optional"): a real password is
          verified and the token issued immediately; the "egf..."
          placeholder (or no password) sends an OTP instead.
    """
    try:
        throttle_ip("sign_in_start")

        if not mobile_no:
            return Response(
                json.dumps({"status": "error", "message": "mobile_no is required"}),
                status=400, mimetype="application/json",
            )

        # ── STEP 1: Look up the Employee whose number is exactly mobile_no ──
        employee = find_employee(mobile_no)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No employee found for the given phone number",
                }),
                status=404, mimetype="application/json",
            )

        employee_id      = employee["name"]
        employee_mobile  = employee["cell_number"]
        employee_user_id = employee.get("user_id")

        policy, error_response = _resolve_login_policy(employee, login_type)
        if error_response:
            return error_response

        password_policy = policy["password_policy"]
        otp_policy      = policy["otp_policy"]

        # ── STEP 2: Password check ───────────────────────────────────────────
        if password_policy == "Mandatory":
            if not password:
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "Password is required",
                    }),
                    status=400, mimetype="application/json",
                )
            if not employee_user_id or not verify_password(employee_id, employee_user_id, password):
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "Invalid password",
                    }),
                    status=401, mimetype="application/json",
                )

        # ── Optional (password or OTP): a real password signs in straight
        # away; the app placeholder (or no password) falls back to OTP. ─────
        if password_policy == "Optional":
            if password and not is_placeholder_password(password):
                if not employee_user_id or not verify_password(employee_id, employee_user_id, password):
                    return Response(
                        json.dumps({
                            "status":  "error",
                            "message": "Invalid password",
                        }),
                        status=401, mimetype="application/json",
                    )
                return _issue_sign_in_token(employee, employee_id, employee_mobile, password_policy, otp_policy)
            return _send_sign_in_otp(employee, password_policy, otp_policy)

        # ── STEP 3: OTP dispatch ─────────────────────────────────────────────
        if otp_policy == "Mandatory":
            return _send_sign_in_otp(employee, password_policy, otp_policy)

        # Password only → already verified above, issue token now.
        return _issue_sign_in_token(employee, employee_id, employee_mobile, password_policy, otp_policy)

    except frappe.RateLimitExceededError:
        return throttled_reply()
    except Exception:
        return failure_reply("otp_generate_for_sign_in")


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Complete sign-in / cold boot and issue the token
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def sign_in_api(mobile_no=None, otp=None, password=None, login_type="sign_in"):
    """
    Complete sign-in (or cold-boot re-verification) and issue the access +
    refresh token.

    The policy comes from get_login_policies — "sign_in_policy" or
    "cold_boot_policy" depending on login_type:

        Password only (Password Authentication, Both on cold boot):
            password must match the employee's login password.
        Optional (password and OTP both "Optional"):
            either otp is verified, or — with no otp — password must match.
        OTP only (OTP Authentication):
            otp is required, single use, with limited tries (auth_core).
        Both:
            otp is required and password must match.

    Sign-in never changes the login password: the token is issued directly
    once the OTP or password is verified, so the app's "egf..." placeholder
    is ignored and a password used on the ERP website stays as it is.

    Params:
        mobile_no  : same phone number passed to otp_generate_for_sign_in().
        otp        : the OTP code entered by the user.
        password   : always required by this API; for OTP-only sign-in the
                     app sends its placeholder.
        login_type : "sign_in" (default) or "cold_boot".
    """
    try:
        throttle_ip("sign_in")

        if not mobile_no or not password:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "mobile_no and password are required",
                }),
                status=400, mimetype="application/json",
            )

        employee = find_employee(mobile_no)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid Employee ID or OTP",
                }),
                status=401, mimetype="application/json",
            )

        employee_id       = employee["name"]
        employee_mobile   = employee["cell_number"]
        employee_user_id  = employee.get("user_id")

        policy, error_response = _resolve_login_policy(employee, login_type)
        if error_response:
            return error_response

        password_policy = policy["password_policy"]
        otp_policy      = policy["otp_policy"]

        if not employee_user_id:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No user account linked to this employee",
                }),
                status=404, mimetype="application/json",
            )

        # ── Verify password first (when mandatory) so a wrong password
        # doesn't consume the OTP. ───────────────────────────────────────────
        if password_policy == "Mandatory" and not verify_password(employee_id, employee_user_id, password):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid password",
                }),
                status=401, mimetype="application/json",
            )

        # ── Optional without an OTP: the password alone must match. ─────────
        if password_policy == "Optional" and not otp and not verify_password(employee_id, employee_user_id, password):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid password",
                }),
                status=401, mimetype="application/json",
            )

        # ── Verify OTP — single use, so it can never be replayed. ───────────
        if otp_policy == "Mandatory" or (otp_policy == "Optional" and otp):
            if not otp:
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "OTP is required",
                    }),
                    status=400, mimetype="application/json",
                )

            if not verify_otp(employee_id, otp):
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "Invalid or expired OTP",
                    }),
                    status=401, mimetype="application/json",
                )

        # ── Verified — issue access + refresh token ──────────────────────────
        return _issue_sign_in_token(employee, employee_id, employee_mobile, password_policy, otp_policy)

    except frappe.RateLimitExceededError:
        return throttled_reply()
    except Exception:
        return failure_reply("sign_in_api")


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Pick the sign-in or cold-boot policy for this request
# ════════════════════════════════════════════════════════════════════════════════

def _resolve_login_policy(employee, login_type):
    """
    Returns (policy, None) or (None, error_response).

    A cold boot with no verification required (High Security off) is
    rejected: the app should just refresh its token via
    refresh_employee_token rather than calling the sign-in endpoints.
    """
    policies = get_login_policies(employee)
    login_type = login_type or "sign_in"

    if login_type == "sign_in":
        return policies["sign_in_policy"], None

    if login_type == "cold_boot":
        if policies["cold_boot_policy"] == POLICY_NONE:
            return None, Response(
                json.dumps({
                    "status":  "error",
                    "message": "No cold boot verification required for this employee",
                }),
                status=400, mimetype="application/json",
            )
        return policies["cold_boot_policy"], None

    return None, Response(
        json.dumps({
            "status":  "error",
            "message": "login_type must be 'sign_in' or 'cold_boot'",
        }),
        status=400, mimetype="application/json",
    )


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Send the sign-in OTP (auth_core.send_otp: random, limited, never logged)
# ════════════════════════════════════════════════════════════════════════════════

def _send_sign_in_otp(employee, password_policy, otp_policy):
    if not send_otp(employee):
        return Response(
            json.dumps({
                "status":  "error",
                "message": "OTP generated but WhatsApp delivery failed",
            }),
            status=500, mimetype="application/json",
        )

    return Response(
        json.dumps({
            "status":      "success",
            "message":     "OTP sent successfully",
            "employee_id": employee["name"],
            "policy": {
                "password_policy": password_policy,
                "otp_policy":      otp_policy,
            },
            "otp_expires_in": OTP_TTL,
        }),
        status=200, mimetype="application/json",
    )


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Issue the access + refresh token, once the caller has proved who they are
# ════════════════════════════════════════════════════════════════════════════════

def _issue_sign_in_token(employee, employee_id, employee_mobile, password_policy, otp_policy):
    token_json = issue_app_tokens(employee.get("user_id"))
    if not token_json:
        return _credentials_refused()

    return Response(
        json.dumps({
            "status": "success",
            "data": {
                "token": token_json,
                "employee": {
                    "id":            employee_id,
                    "employee_name": employee.get("employee_name"),
                    "phone":         employee_mobile,
                    "email":         employee.get("email_id"),
                },
                "password_policy": password_policy,
                "otp_policy":      otp_policy,
                "time": str(frappe.utils.now_datetime()),
            }
        }),
        status=200,
        mimetype="application/json",
    )
