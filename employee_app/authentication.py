import json
import random
import re
import base64
import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import check_password, update_password
from werkzeug.wrappers import Response

from employee_app.gauth import _authenticate, _issue_bearer_token


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Look up an Employee's login policy by phone number (no OTP sent)
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_employee_login_policy(mobile=None):
    try:

        if not mobile:
            return Response(
                json.dumps({"status": "error", "message": "mobile is required"}),
                status=400, mimetype="application/json",
            )

        employee_row = _find_employee_by_mobile(mobile)

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
            }),
            status=200, mimetype="application/json",
        )

    except Exception as e:
        frappe.log_error(title="get_employee_login_policy error", message=frappe.get_traceback())
        return Response(
            json.dumps({"status": "error", "message": str(e)}),
            status=500, mimetype="application/json",
        )


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
def generate_and_send_otp(mobile_no=None):
    try:
        if not mobile_no:
            return Response(
                json.dumps({"status": "error", "message": "mobile_no is required"}),
                status=400, mimetype="application/json",
            )

        # ── STEP 1: Look up the Employee whose mobile_no matches the payload ──
        employee = _find_employee_by_mobile(mobile_no)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No employee found for the given phone number",
                }),
                status=404, mimetype="application/json",
            )

        employee_id     = employee["name"]
        employee_mobile = employee["cell_number"]

        # ── Fetch WhatsApp Saudi config ────────────────────────────────────────
        wa_config   = frappe.get_doc("Whatsapp Saudi")
        is_testing  = wa_config.get("testing")        # testing checkbox

        # ── STEP 2: Generate OTP ────────────────────────────────────────────────
        # When testing is enabled, use the fixed testing_otp value instead of
        # generating a random one, so testers/automation can rely on a known code.
        if is_testing:
            otp = wa_config.get("testing_otp")
        else:
            otp = str(random.randint(100000, 999999))

        # ── STEP 3: Cache OTP against mobile number (expires in 5 min) ────────
        otp_expires_in_sec = 300
        key = f"otp:{employee_mobile}"
        frappe.cache().set_value(key, otp, expires_in_sec=otp_expires_in_sec)

        # ── STEP 4: If testing — skip WhatsApp, return OTP in response ────────
        if is_testing:
            frappe.log_error(
                title="[OTP] Testing mode — OTP not sent via WhatsApp",
                message=f"employee_id={employee_id} | mobile={employee_mobile} | otp={otp}"
            )
            return Response(
                json.dumps({
                    "status":         "success",
                    "message":        "OTP sent successfully",   # ← returned only in testing mode
                    "otp_expires_in": otp_expires_in_sec,
                }),
                status=200, mimetype="application/json",
            )

        # ── STEP 5: Live mode — send via WhatsApp, never expose OTP ──────────
        result = frappe.call(
            "whatsapp_saudi.overrides.whtatsapp_notification.send_otp",
            phone=_clean_phone_number(employee_mobile),
            otp_code=otp,
        )

        # send_otp() (whatsapp_saudi) returns different shapes depending on
        # the configured provider — success is either {"success": True, ...}
        # or {"status": "success", ...}; both are treated as success here.
        is_delivered = isinstance(result, dict) and (
            result.get("success") is True or result.get("status") == "success"
        )

        if not is_delivered:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "OTP generated but WhatsApp delivery failed",
                    "detail":  result.get("error") if isinstance(result, dict) else None,
                }),
                status=500, mimetype="application/json",
            )

        return Response(
            json.dumps({
                "status":         "success",
                "message":        "OTP sent successfully",
                "otp_expires_in": otp_expires_in_sec,
                # otp intentionally omitted in live mode
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
def sign_up_api(mobile_no=None, otp=None, password=None):
    """
    Verify the OTP sent via generate_and_send_otp, save the employee's
    password, and — on success — issue an OAuth2 access token.

    Driven by the sign-up policy from get_login_policies (Employee's
    Authentication field):
        - OTP is mandatory for every Authentication type.
        - Password Authentication / Both: the employee must create a password;
          missing or an app placeholder ("egf...") = rejected.
        - Optional: the employee may create a password or not. If they do,
          custom_user_created_password is turned on. Their sign-in /
          cold-boot policy stays Optional either way (password or OTP).
        - OTP Authentication: no password is created.

    Params:
        mobile_no : phone number used to look up the Employee and the OTP
                    cache key.
        otp       : the OTP code entered by the user.
        password  : always required, because the OAuth2 password grant needs
                    it. When the employee doesn't create one (OTP
                    Authentication, or Optional without a password), the
                    frontend sends its auto-generated "egf..." placeholder.
                    Saved as the linked User's login password.
    """
    try:
        if not mobile_no:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "mobile_no is required",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

        frappe.log_error(
            title="Customer OTP login attempt",
            message=f"{mobile_no}",
        )

        # ── STEP 1: Look up the Customer whose mobile_no matches the payload ──
        employee = _find_employee_by_mobile(mobile_no)

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
        sign_up_policy  = get_login_policies(employee)["sign_up_policy"]
        password_policy = sign_up_policy["password_policy"]
        otp_policy      = sign_up_policy["otp_policy"]

        # ── STEP 2: Validate inputs against the sign-up policy before the
        # OTP is consumed, so a rejected request doesn't burn the OTP.
        if not password:
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

        # ── STEP 3: OTP check ────────────────────────────────────────────────
        if otp:
            key        = f"otp:{employee_cell_number}"
            cached_otp = frappe.cache().get_value(key)

            if not cached_otp or str(cached_otp) != str(otp):
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "Invalid or expired OTP",
                        "user_count": 0,
                    }),
                    status=401, mimetype="application/json",
                )
            frappe.cache().delete_value(key)

        # ── STEP 4: Save the password — a real one the employee created, or
        # the app placeholder. The token request below needs it either way.
        # _update_user_created_password_flag records which one it was, so
        # sign-in knows whether the employee has a password of their own.
        set_employee_password(employee_id, password)
        _write_custom_password(employee_id, password)
        _update_user_created_password_flag(employee_id, password)

        # ── GET employee phone from primary contact ─────────────────────────
        employee_phone = None
        try:
            primary_contact = employee.get("employee_primary_contact")
            if primary_contact:
                phone_row = frappe.db.get_value(
                    "Contact Phone",
                    {"parent": primary_contact},
                    "phone",
                    as_dict=True
                )
                if phone_row:
                    employee_phone = phone_row.phone
        except Exception:
            employee_phone = None

        # ── STEP 5: Derive app_key from the site's OAuth Client ─────────────
        auth_client_name = frappe.db.get_value("OAuth Client", {}, "name")
        if not auth_client_name:
            return Response(
                json.dumps({"status": "error", "message": "No OAuth Client found"}),
                status=500,
                mimetype="application/json"
            )

        auth_client = frappe.get_doc("OAuth Client", auth_client_name)

        app_name = auth_client.app_name
        if not app_name:
            return Response(
                json.dumps({"status": "error", "message": "App name missing in OAuth Client"}),
                status=500,
                mimetype="application/json"
            )

        client_secret = auth_client.client_secret
        if not client_secret:
            return Response(
                json.dumps({"status": "error", "message": "Client secret missing in OAuth Client"}),
                status=500,
                mimetype="application/json"
            )

        app_key = base64.b64encode(app_name.encode()).decode("utf-8")

        # ── STEP 6: Issue the OAuth2 token via the shared helper ────────────
        error_response, token_json = issue_oauth_tokens_for_app(app_key, employee_id,password)

        if error_response:
            return error_response

        frappe.db.set_value("Employee", employee_id, "custom_employee_has_signed_up", 1)

        return Response(
            json.dumps({
                "status": "success",
                "data": {
                    "token": token_json,
                    "employee": {
                        "id":            employee_id,
                        "employee_name": employee.get("employee_name"),
                        "phone":         employee_phone or employee_cell_number,
                        "email":         employee.get("email_id"),
                    },
                    "time": str(frappe.utils.now_datetime()),
                }
            }),
            status=200,
            mimetype="application/json",
        )

    except Exception as e:
        frappe.log_error(title="verify_otp error", message=frappe.get_traceback())
        return Response(
            json.dumps({"status": "error", "message": str(e), "user_count": 0}),
            status=500, mimetype="application/json",
        )


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Write custom_password as a literal value, no hashing
# ════════════════════════════════════════════════════════════════════════════════

def _write_custom_password(employee_id, password):
    """
    custom_password is fieldtype "Password" on the Employee doctype. Going
    through doc.save() (or anything that triggers Document controller hooks)
    would route a Password-fieldtype value into Frappe's encrypted __Auth
    table instead of the plain tabEmployee column — which is exactly what we
    do NOT want here, since the requirement is: store precisely what was
    passed in, unmodified, in custom_password itself.

    To guarantee that, this bypasses frappe.db.set_value / doc.save() and
    issues a direct SQL UPDATE against the table column, then commits
    explicitly so the write is not left pending on the request transaction.

    NOTE: because the field's fieldtype is still Password, the Desk UI will
    still render it as masked dots when you open the Employee form — that is
    a client-side rendering behavior tied to the fieldtype and is unrelated
    to whether the value was actually saved. This function guarantees the
    literal value is what lands in the database column; it does not (and
    cannot) change how the Password widget displays it in Desk.
    """
    frappe.db.sql(
        """
        update `tabEmployee`
        set custom_employee_password = %s
        where name = %s
        """,
        (password, employee_id),
    )
    frappe.db.commit()


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
    sign_in.py reads this flag so an OTP sign-in never overwrites a password
    the employee created.
    """
    frappe.db.set_value(
        "Employee", employee_id, "custom_user_created_password", 0 if is_placeholder_password(password) else 1
    )


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Mirror a newly-set User password into the linked Employee
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def sync_user_password_to_employee(user, password):
    """
    Called from public/sync_user_password.js on the User doctype whenever
    someone fills in "Set New Password" and saves. Looks up the Employee
    whose user_id matches this User and writes the password into
    custom_employee_password via _write_custom_password, so it lands as the same
    literal, unhashed value that authentication.py itself reads back later.
    """


    employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if employee_id:
        _write_custom_password(employee_id, password)


def _find_employee_by_mobile(mobile_no):
    """
    Matches on the last 9 digits so formatting differences between the
    incoming payload (e.g. 05xxxxxxxx, +9665xxxxxx, 9665xxxxxx) and however
    the number is stored on Employee don't cause a false miss.
    """
    local_number = _extract_local_number(mobile_no)

    if not local_number:
        return None

    rows = frappe.db.sql(
        """
        select
            name,
            employee_name,
            cell_number,
            user_id,
            custom_authentication,
            custom_high_security,
            custom_user_created_password
        from `tabEmployee`
        where cell_number like %s
        limit 1
        """,
        (f"%{local_number}",),
        as_dict=True,
    )

    return rows[0] if rows else None



@frappe.whitelist()
def refresh_employee_token(refresh_token):
    """
    Create a new access token using a refresh token.
    Unchanged by this customization — refreshing is independent of whether
    the employee originally logged in via password or OTP.

    Params:
        refresh_token: The refresh token string received during initial login
    """
    frappe.log_error(
        title="Employee token refresh attempt",
        message=f"Refresh token used: {refresh_token[:20]}..." if refresh_token else "No token provided",
    )

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
        # Done in-process: revoke the old token and issue a new pair, instead
        # of calling Frappe's oauth2.get_token endpoint over HTTP.
        old = frappe.db.get_value(
            "OAuth Bearer Token",
            {"refresh_token": refresh_token, "status": "Active"},
            ["name", "client", "user", "scopes"],
            as_dict=True,
        )
        if not old or not frappe.db.get_value("User", old.user, "enabled"):
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "Invalid or expired refresh token",
                    "detail": {"error": "invalid_grant"},
                }),
                status=401,
                mimetype="application/json",
            )

        frappe.db.set_value("OAuth Bearer Token", old.name, "status", "Revoked")
        new_token_data = _issue_bearer_token(old.user, old.client, old.scopes)

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

    except Exception as e:
        return Response(
            json.dumps({
                "status": "error",
                "message": str(e),
            }),
            status=500,
            mimetype="application/json",
        )


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC — Set a new login password for the User linked to an Employee
# ════════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def set_employee_password(employee_id=None, password=None):
    """
    Set `password` as the new login password for the User linked to
    `employee_id` (no old-password check — direct reset).

    Looks up the Employee, resolves its user_id, and updates that User's
    normal (hashed) Frappe password via update_password — this is unrelated
    to the plain-text custom_password field written by verify_otp.

    Params:
        employee_id : Employee doctype name
        password    : New password to set for the employee's linked User
    """
    try:
        if not employee_id or not password:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "employee_id and password are required",
                }),
                status=400, mimetype="application/json",
            )

        employee = frappe.db.get_value(
            "Employee", employee_id, ["name", "user_id"], as_dict=True
        )

        if not employee:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "Employee not found",
                }),
                status=404, mimetype="application/json",
            )

        if not employee.user_id:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "No user account linked to this employee",
                }),
                status=404, mimetype="application/json",
            )

        update_password(employee.user_id, password)

        return Response(
            json.dumps({
                "status":      "success",
                "message":     "Password updated successfully",
                "employee_id": employee.name,
                "user_id":     employee.user_id,
            }),
            status=200, mimetype="application/json",
        )

    except Exception as e:
        frappe.log_error(title="set_employee_password error", message=frappe.get_traceback())
        return Response(
            json.dumps({"status": "error", "message": str(e)}),
            status=500, mimetype="application/json",
        )




def issue_oauth_tokens_for_app(app_key, employee_id,password):
    """
    Decode app_key, resolve the matching OAuth Client, load the employee's
    own login user (Employee.user_id), check the password in-process and
    create an OAuth Bearer Token directly (Frappe no longer supports the
    OAuth password grant through oauth2.get_token).

    Returns a 2-tuple:
        (None, token_json)        on success — token_json is a dict with
                                   access_token, token_type, expires_in,
                                   refresh_token and scope
        (error_response, None)    on failure — error_response is a ready-to
                                   -return werkzeug Response; just
                                   `return error_response` from the caller.
    """

    # ── STEP 0: Tenant service-account credentials ─────────────────────────
    try:
        employee_doc = frappe.get_doc("Employee", employee_id)
        username = employee_doc.user_id
        # custom_password is written as a literal value straight into the
        # tabEmployee column (see _write_custom_password) — it never goes
        # through __Auth, so it must be read back the same way rather than
        # via get_decrypted_password (which only looks in __Auth).


    except Exception as e:
        return Response(
            json.dumps({
                "status": "error",
                "message": f"Customer user settings not configured: {str(e)}",
                "user_count": 0,
            }),
            status=500,
            mimetype="application/json",
        ), None

    if not username or not password:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Employee login credentials not configured",
                "user_count": 0,
            }),
            status=500,
            mimetype="application/json",
        ), None

    # ── STEP 1: Decode app_key ──────────────────────────────────────────────
    try:
        decoded_app_key = base64.b64decode(app_key).decode("utf-8")
    except Exception:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Security Parameters are not valid",
                "user_count": 0,
            }),
            status=401,
            mimetype="application/json",
        ), None

    # ── STEP 2: Fetch OAuth Client by app_name ──────────────────────────────
    oauth_client = frappe.db.get_value(
        "OAuth Client",
        {"app_name": decoded_app_key},
        ["name", "scopes"],
        as_dict=True,
    )

    if not oauth_client:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Security Parameters are not valid",
                "user_count": 0,
            }),
            status=401,
            mimetype="application/json",
        ), None

    # ── STEP 3: Check the password in-process ───────────────────────────────
    # Frappe no longer supports the OAuth password grant, so the password is
    # checked here and the token created directly instead of calling
    # frappe.integrations.oauth2.get_token over HTTP.
    user = _authenticate(username, password)
    if not user:
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
        ), None

    # ── STEP 4: Issue the token ─────────────────────────────────────────────
    try:
        return None, _issue_bearer_token(user, oauth_client.name, oauth_client.scopes)
    except Exception as e:
        frappe.log_error(title="issue_oauth_tokens_for_app: token insert failed", message=str(e))
        return Response(
            json.dumps({
                "status": "error",
                "message": "Could not issue token",
                "user_count": 0,
            }),
            status=500,
            mimetype="application/json",
        ), None

@frappe.whitelist(allow_guest=True)
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

        except Exception as e:
            return Response(
                json.dumps({"message": str(e), "user_count": 0}),
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
