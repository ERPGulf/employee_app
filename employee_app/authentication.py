import json
from typing import Any
import base64
import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import update_password
from werkzeug.wrappers import Response

from employee_app.auth_core import (
    OTP_TTL,
    failure_reply,
    find_employee,
    is_privileged,
    issue_app_tokens,
    log_failure,
    erp_password_setup_allowed,
    password_setup_allowed,
    password_too_weak,
    rotate_refresh_token,
    send_otp,
    throttle_ip,
    throttled_reply,
    verify_otp,
    verify_password,
)
from employee_app.gauth import _authenticate, _issue_bearer_token


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Look up an Employee's login policy by phone number (no OTP sent)
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_employee_login_policy(mobile: str | int | None = None):
    try:
        throttle_ip("login_policy")

        if not mobile:
            return Response(
                json.dumps({"status": "error", "message": "mobile is required"}),
                status=400, mimetype="application/json",
            )

        employee_row = find_employee(mobile)

        if not employee_row:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No employee found for the given phone number",
                }),
                status=404, mimetype="application/json",
            )

        employee_id = employee_row["name"]
        employee    = frappe.get_doc("Employee", employee_id)
        policies    = get_login_policies(employee)

        return Response(
            json.dumps({
                "status":            "success",
                "employee_id":       employee_id,
                "authentication":    policies["authentication"],
                "high_security":     policies["high_security"],
                "sign_up_policy":    policies["sign_up_policy"],
                "sign_in_policy":    policies["sign_in_policy"],
                "cold_boot_policy":  policies["cold_boot_policy"],
                "employee_has_existing_password": bool(employee.custom_user_created_password),
                "employee_has_signed_up": bool(employee.custom_employee_has_signed_up),
                # The app offers Create / Reset password only on true. create_new_password
                # enforces the same rule again when it changes the password.
                "otp_verified_password_setup": password_setup_allowed(employee),
                # Separate offer for OTP-only employees: a password for the ERP website.
                "erp_web_password_setup_allowed": erp_password_setup_allowed(employee),
            }),
            status=200, mimetype="application/json",
        )

    except frappe.RateLimitExceededError:
        return throttled_reply()
    except Exception:
        return failure_reply("get_employee_login_policy")


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Derive sign-up / sign-in / cold-boot policies from the Employee's
# "Authentication" (custom_authentication) and "High Security"
# (custom_high_security) fields
# ════════════════════════════════════════════════════════════════════════════════

AUTH_PASSWORD = "Password Authentication"
AUTH_OTP      = "OTP Authentication"
AUTH_OPTIONAL = "Optional"
AUTH_BOTH     = "Both"

POLICY_PASSWORD = {"password_policy": "Mandatory", "otp_policy": "No"}
POLICY_OTP      = {"password_policy": "No",        "otp_policy": "Mandatory"}
POLICY_BOTH     = {"password_policy": "Mandatory", "otp_policy": "Mandatory"}
POLICY_NONE     = {"password_policy": "No",        "otp_policy": "No"}
POLICY_OPTIONAL = {"password_policy": "Optional",  "otp_policy": "Optional"}


def get_login_policies(employee):
    """
    `employee` is an Employee doc or a dict row carrying custom_authentication
    and custom_high_security.

        Authentication           Sign up            Sign in            Cold boot
        Password Authentication  password + OTP     password           password
        OTP Authentication       OTP                OTP                OTP
        Optional                 OTP (+ optional    password or OTP    password or OTP
                                 password)          (both Optional,    (both Optional)
                                                    even after the
                                                    employee creates
                                                    a password)
        Both                     password + OTP     password + OTP     password (OTP No)

    Cold boot verification only applies when High Security is ticked;
    otherwise the cold boot policy is POLICY_NONE.
    The sign-up API never changes these policies, even when the employee
    creates a password.

    An empty Authentication is treated as "Password Authentication", the
    first option of the Select field and what the Employee form displays.
    """
    authentication = employee.get("custom_authentication") or AUTH_PASSWORD
    high_security  = bool(employee.get("custom_high_security"))

    if authentication == AUTH_OTP:
        sign_up_policy = sign_in_policy = POLICY_OTP
    elif authentication == AUTH_OPTIONAL:
        sign_up_policy = {"password_policy": "Optional", "otp_policy": "Mandatory"}
        sign_in_policy = POLICY_OPTIONAL
    elif authentication == AUTH_BOTH:
        sign_up_policy = sign_in_policy = POLICY_BOTH
    else:
        sign_up_policy = POLICY_BOTH
        sign_in_policy = POLICY_PASSWORD

    if not high_security:
        cold_boot_policy = POLICY_NONE
    elif authentication == AUTH_BOTH:
        cold_boot_policy = POLICY_PASSWORD
    else:
        cold_boot_policy = sign_in_policy

    return {
        "authentication":   authentication,
        "high_security":    high_security,
        "sign_up_policy":   dict(sign_up_policy),
        "sign_in_policy":   dict(sign_in_policy),
        "cold_boot_policy": dict(cold_boot_policy),
    }


def is_placeholder_password(password):
    """The frontend sends an auto-generated "egf..." password when the employee hasn't chosen one."""
    return str(password or "").lower().startswith("egf")


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Generate & send OTP, matched by phone number
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def generate_and_send_otp(mobile_no: str | int | None = None):
    """Send a random OTP by WhatsApp to the employee with exactly this number.
    Per-employee limits apply (auth_core.issue_otp); the OTP is never returned
    or logged, and provider replies never reach the caller."""
    try:
        throttle_ip("send_otp")

        if not mobile_no:
            return Response(
                json.dumps({"status": "error", "message": "mobile_no is required"}),
                status=400, mimetype="application/json",
            )

        employee = find_employee(mobile_no)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No employee found for the given phone number",
                }),
                status=404, mimetype="application/json",
            )

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
                "status":         "success",
                "message":        "OTP sent successfully",
                "otp_expires_in": OTP_TTL,
            }),
            status=200, mimetype="application/json",
        )

    except Exception as e:
        frappe.log_error(title="send_otp error", message=frappe.get_traceback())
        return Response(
            json.dumps({"status": "error", "message": str(e)}),
            status=500, mimetype="application/json",
        )



def _extract_local_number(phone):
    """Strip everything but digits and return the last 9 (Saudi local length)."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-9:] if len(digits) >= 9 else digits




def _send_otp_whatsapp(mobile_no, otp):
    try:
        from whatsapp_saudi.overrides.whtatsapp_notification import send_whatsapp_text

        phone = _clean_phone_number(mobile_no)

        frappe.log_error(title="OTP WhatsApp send", message=f"To: {phone} | OTP: {otp}")

        message = (
            f"رمز التحقق لتسجيل الدخول هو *{otp}*.\n"
            "هذا الرمز صالح لمدة 5 دقائق. يُرجى عدم مشاركته مع أي شخص.\n\n"
            f"Your login verification code is *{otp}*. "
            "This code is valid for 5 minutes. Please do not share it with anyone."
        )

        result = send_whatsapp_text(message=message, phone=phone)


        frappe.log_error(title="OTP WhatsApp response", message=frappe.as_json(result))

        if isinstance(result, dict) and result.get("status") == "success":
            return {"success": True}

        frappe.log_error(title="OTP WhatsApp send failed", message=frappe.as_json(result))
        return {"success": False, "error": result}

    except Exception as e:
        frappe.log_error(title="OTP WhatsApp exception", message=frappe.get_traceback())
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Clean phone number (unchanged)
# ════════════════════════════════════════════════════════════════════════════════

def _clean_phone_number(number):
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


@frappe.whitelist()
def sign_up_api(mobile_no: str | int | None = None, otp: str | int | None = None, password: Any = None):
    """
    First-time enrollment: verify the OTP sent via generate_and_send_otp,
    save a password the employee chose, and issue an OAuth2 access token.

    Driven by the sign-up policy from get_login_policies (Employee's
    Authentication field):
        - OTP is mandatory for every Authentication type.
        - Password Authentication / Both: the employee must create a password;
          missing or an app placeholder ("egf...") = rejected.
        - Optional: the employee may create a password or not. If they do,
          custom_user_created_password is turned on. Their sign-in /
          cold-boot policy stays Optional either way (password or OTP).
        - OTP Authentication: no password is created.

    An employee who has already signed up is refused (409): later password
    changes go through create_new_password and its rule. To re-enroll someone,
    untick "Employee Has Signed Up" on the Employee.

    Params:
        mobile_no : phone number used to look up the Employee.
        otp       : the OTP code entered by the user.
        password  : always required. When the employee doesn't create one
                    (OTP Authentication, or Optional without a password), the
                    app sends its "egf..." placeholder, which is ignored: it
                    never becomes the login password.
    """
    try:
        throttle_ip("sign_up")

        if not mobile_no:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "mobile_no is required",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        # ── STEP 1: Look up the Employee whose number is exactly mobile_no ──
        employee = find_employee(mobile_no)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid Employee ID or Password",
                    "user_count": 0,
                }),
                status=401, mimetype="application/json",
            )

        employee_id     = employee["name"]
        employee_cell_number = employee["cell_number"]
        user_id         = employee.get("user_id")
        sign_up_policy  = get_login_policies(employee)["sign_up_policy"]
        password_policy = sign_up_policy["password_policy"]
        otp_policy      = sign_up_policy["otp_policy"]

        if employee.get("custom_employee_has_signed_up"):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Employee has already signed up",
                    "user_count": 0,
                }),
                status=409, mimetype="application/json",
            )

        # ── STEP 2: Validate inputs against the sign-up policy before the
        # OTP is consumed, so a rejected request doesn't burn the OTP.
        if not password or not isinstance(password, str):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "password is required",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        if password_policy == "Mandatory" and is_placeholder_password(password):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Please create a password to sign up",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        if otp_policy == "Mandatory" and not otp:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "OTP is required",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        chosen_password = not is_placeholder_password(password)

        if not user_id or not frappe.db.get_value("User", user_id, "enabled"):
            return _credentials_refused()

        # An admin account keeps the password it uses in Desk: sign-up checks it, never sets it.
        save_password = chosen_password and not is_privileged(user_id)
        if chosen_password and not save_password and not verify_password(employee_id, user_id, password):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid password",
                    "user_count": 0,
                }),
                status=401, mimetype="application/json",
            )

        if save_password and password_too_weak(user_id, password):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Please choose a different password",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        # ── STEP 3: OTP check — single use, limited tries (auth_core) ──────
        if otp and not verify_otp(employee_id, otp):
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "Invalid or expired OTP",
                    "user_count": 0,
                }),
                status=401, mimetype="application/json",
            )

        # ── STEP 4: Record the sign-up, and save a password only when the
        # employee chose one. The app's placeholder never becomes the login
        # password, so it can't replace a password used on the ERP website.
        # Flags first: update_password commits when it ends Desk sessions,
        # and issuing the token commits too.
        if chosen_password:
            _update_user_created_password_flag(employee_id, password)
        frappe.db.set_value("Employee", employee_id, "custom_employee_has_signed_up", 1)
        if save_password:
            update_password(user_id, password, logout_all_sessions=True)

        # ── STEP 5: Issue the token directly; the OTP proved who this is ────
        token_json = issue_app_tokens(user_id)
        if not token_json:
            frappe.db.rollback()
            return _credentials_refused()

        return Response(
            json.dumps({
                "status": "success",
                "data": {
                    "token": token_json,
                    "employee": {
                        "id":            employee_id,
                        "employee_name": employee.get("employee_name"),
                        "phone":         employee_cell_number,
                        "email":         employee.get("email_id"),
                    },
                    "time": str(frappe.utils.now_datetime()),
                }
            }),
            status=200,
            mimetype="application/json",
        )

    except frappe.RateLimitExceededError:
        return throttled_reply()
    except Exception:
        return failure_reply("sign_up_api")


def _credentials_refused():
    """The reply a disabled or missing login user has always got."""
    return Response(
        json.dumps({
            "status": "error",
            "message": "Invalid credentials or unauthorized",
            "detail": {
                "error": "invalid_grant",
                "error_description": "Invalid credentials given.",
            },
        }),
        status=401,
        mimetype="application/json",
    )


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Flag whether the password was actually chosen by the employee
# ════════════════════════════════════════════════════════════════════════════════

def _update_user_created_password_flag(employee_id, password):
    """
    The frontend auto-generates a placeholder password (e.g. "egf_934") and
    sends it along whenever the employee hasn't actually set one — a real
    password an employee chooses (e.g. "Aysha@123") won't follow that
    "egf..." pattern. So custom_user_created_password is turned on only when
    the incoming password is not a placeholder (see is_placeholder_password).
    get_employee_login_policy reports it as employee_has_existing_password.
    """
    frappe.db.set_value(
        "Employee", employee_id, "custom_user_created_password", 0 if is_placeholder_password(password) else 1
    )



@frappe.whitelist()
def refresh_employee_token(refresh_token: Any):
    """
    Create a new access token using a refresh token. Each refresh token works
    once; one presented again ends every session of its user
    (auth_core.rotate_refresh_token).

    Params:
        refresh_token: The refresh token string received during initial login
    """
    # Keep raw JSON intact: rotate_refresh_token rejects nonstrings with the API's 401 response.
    if not refresh_token:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Refresh token is required",
            }),
            status=400,
            mimetype="application/json",
        )

    try:
        new_token_data = rotate_refresh_token(refresh_token)
        if not new_token_data:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "Invalid or expired refresh token",
                    "detail": {"error": "invalid_grant"},
                }),
                status=401,
                mimetype="application/json",
            )

        return Response(
            json.dumps({
                "status": "success",
                "data": {
                    "token": new_token_data,
                    "time": str(frappe.utils.now_datetime()),
                }
            }),
            status=200,
            mimetype="application/json",
        )

    except Exception:
        return failure_reply("refresh_employee_token")


# Existing public service-token bootstrap; configured credentials do not identify the caller.
# Tenants must provision a limited service user; service_gate enforcement remains tenant controlled.
@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def master_token():
        try:
            try:
                doc=frappe.get_doc("Checkin App Setting")
                api_key = doc.user
                api_secret = doc.password
                key=doc.app_key



                app_key = base64.b64decode(key).decode("utf-8")

            except Exception as e:

                return Response(
                    json.dumps(
                        {"message": "Security Parameters are not valid", "user_count": 0}
                    ),
                    status=401,
                    mimetype="application/json",
                )

            client = frappe.db.get_value(
                "OAuth Client",
                {"app_name": app_key},
                ["name", "scopes"],
                as_dict=True,
            )

            if not client:

                return Response(
                    json.dumps(
                        {"message": "Security Parameters are not valid", "user_count": 0}
                    ),
                    status=401,
                    mimetype="application/json",
                )

            # Password checked and token created in-process — Frappe no longer
            # supports the OAuth password grant via oauth2.get_token.
            user = _authenticate(api_key, api_secret)
            if not user:
                return Response(
                    json.dumps(
                        {"error": "invalid_grant", "error_description": "Invalid credentials given."}
                    ),
                    status=401,
                    mimetype="application/json",
                )

            return Response(
                json.dumps({
                    "data": _issue_bearer_token(user, client.name, client.scopes),
                }),
                status=200,
                mimetype="application/json",
            )

        except Exception:
            return Response(
                json.dumps({"message": "Something went wrong", "ref": log_failure("master_token"), "user_count": 0}),
                status=500,
                mimetype="application/json",
            )

# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Cold boot: re-verify an already signed-up employee when the app
# restarts. Follows the "cold_boot_policy" from get_login_policies:
#
#     Authentication           High Security on     High Security off
#     Password Authentication  password             no verification
#     OTP Authentication       OTP                  no verification
#     Optional                 password or OTP      no verification
#     Both                     password (OTP No)    no verification
#
# With no verification required the APIs return 400 — the app should just
# refresh its token via refresh_employee_token instead.
# Same request / response shape as otp_generate_for_sign_in and sign_in_api.
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def otp_generate_for_cold_boot(mobile_no=None, password=None):
    """
    Step 1 of cold boot.

        Password only : password is checked and the token issued in this call.
        OTP only      : an OTP is sent; finish with cold_boot_api.
        Optional      : a real password issues the token straight away; the
                        "egf..." placeholder (or no password) sends an OTP.
    """
    # Imported here: sign_in imports from this module at load time.
    from employee_app.sign_in import otp_generate_for_sign_in

    return otp_generate_for_sign_in(mobile_no=mobile_no, password=password, login_type="cold_boot")


@frappe.whitelist()
def cold_boot_api(mobile_no=None, otp=None, password=None):
    """
    Step 2 of cold boot — verify the OTP (and password when mandatory) and
    issue a fresh access + refresh token.
    """
    from employee_app.sign_in import sign_in_api

    return sign_in_api(mobile_no=mobile_no, otp=otp, password=password, login_type="cold_boot")
