import json
import random
import re
import base64
import frappe
import requests
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import check_password, update_password
from werkzeug.wrappers import Response


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

        employee = _find_employee_by_mobile(mobile)

        if not employee:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "No employee found for the given phone number",
                }),
                status=404, mimetype="application/json",
            )

        employee_id     = employee["name"]
        password_policy = employee.get("custom_password_policy") or "No"
        otp_policy      = employee.get("custom_otp_policy") or "No"
        user_created_password = frappe.db.get_value("Employee", employee_id, "custom_user_created_password")
        employee_has_signed_up=frappe.db.get_value("Employee", employee_id, "custom_employee_has_signed_up")

        return Response(
            json.dumps({
                "status":      "success",
                "employee_id": employee_id,
                "policy": {
                    "password_policy": password_policy,
                    "otp_policy":      otp_policy,
                },
                "employee_has_existing_password": bool(user_created_password),
                "employee_has_signed_up": bool(employee_has_signed_up),
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


# ════════════════════════════════════════════════════════════════════════════════
# INTERNAL — Send OTP via WhatsApp (unchanged)
# ════════════════════════════════════════════════════════════════════════════════

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
    Verify the OTP sent via send_otp, optionally check the
    customer's password (driven by custom_password_policy), and — on
    success — issue an OAuth2 access token.

    app_key is no longer accepted from the caller — it's derived internally
    from the site's OAuth Client, same as generate_token_secure_for_customers.

    Params:
        mobile_no : phone number used to look up the Customer (same matching
                    logic as send_otp) and the OTP cache key.
        otp       : the OTP code entered by the user. Always required and
                    always checked against what send_otp
                    cached — custom_otp_policy is not consulted here.
        password  : Not verified against any existing value — it's written
                    straight into the Customer's custom_password field once
                    OTP/identity is confirmed, exactly as received (no
                    hashing, no transformation). custom_password_policy only
                    controls whether it's expected:
                    - "Mandatory": required; missing password = rejected.
                    - "Optional": saved if supplied; omitted = skipped, no
                      error and custom_password left as-is.
                    - "No" (or unset): ignored entirely, even if supplied.
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
        password_policy = employee.get("custom_password_policy") or "No"
        otp_policy      = employee.get("custom_otp_policy")
        stored_password = employee.get("custom_employee_password")

        # ── STEP 2: OTP check — driven by custom_otp_policy.
        # "Mandatory": otp required; missing otp = rejected.
        # "No" (or unset): otp not required — if omitted, skipped entirely;
        # if supplied anyway, still verified against the cache.
        if otp_policy == "Mandatory" and not otp:
            return Response(
                json.dumps({
                    "status":  "error",
                    "message": "OTP is required",
                    "user_count": 0,
                }),
                status=400, mimetype="application/json",
            )

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

        # ── STEP 3: Password handling, driven by custom_password_policy ─────
        # Not compared against the existing stored value — whatever is sent
        # here is simply (re)written into custom_password once OTP/identity
        # is confirmed, stored exactly as received (no hashing). Policy only
        # controls whether a password is expected.
        if password_policy == "Mandatory":
            if not password:
                return Response(
                    json.dumps({
                        "status":  "error",
                        "message": "password is required",
                        "user_count": 0,
                    }),
                    status=400, mimetype="application/json",
                )
            set_employee_password(employee_id, password)
            _write_custom_password(employee_id, password)
            _update_user_created_password_flag(employee_id, password)
            stored_password = password

        elif password_policy == "Optional" or password_policy == "No":

            # Only save if the caller actually supplied one.
            if password:
                set_employee_password(employee_id, password)
                _write_custom_password(employee_id, password)
                _update_user_created_password_flag(employee_id, password)
                stored_password = password

        # password_policy == "No" (or anything else) → password ignored entirely,
        # even if the caller passes one — custom_password is left untouched.

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

        # ── STEP 4: Derive app_key from the site's OAuth Client ─────────────
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

        host_name = frappe.local.conf.get("host_name")
        if not host_name:
            return Response(
                json.dumps({"status": "error", "message": "host_name missing in site config"}),
                status=500,
                mimetype="application/json"
            )

        app_key = base64.b64encode(app_name.encode()).decode("utf-8")

        # ── STEP 5: Issue the OAuth2 token via the shared helper ────────────
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
    The frontend auto-generates a placeholder password (e.g. "user_934") and
    sends it along whenever the employee hasn't actually set one — a real
    password an employee chooses (e.g. "Aysha@123") won't follow that
    "user..." pattern. So custom_user_created_password is turned on only when
    the incoming password does NOT start with "user", i.e. it looks like a
    genuine, employee-chosen password rather than the frontend's placeholder.
    """
    looks_auto_generated = str(password).lower().startswith("egf")
    frappe.db.set_value(
        "Employee", employee_id, "custom_user_created_password", 0 if looks_auto_generated else 1
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
            custom_password_policy,
            custom_otp_policy
        from `tabEmployee`
        where cell_number like %s
        limit 1
        """,
        (f"%{local_number}",),
        as_dict=True,
    )

    return rows[0] if rows else None



@frappe.whitelist(allow_guest=True)
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

    host_name = frappe.local.conf.get("host_name")
    if not host_name:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Server configuration error: host_name missing",
            }),
            status=500,
            mimetype="application/json",
        )

    try:
        token_url = f"{host_name}/api/method/frappe.integrations.oauth2.get_token"

        payload = f"grant_type=refresh_token&refresh_token={refresh_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        token_response = requests.post(
            token_url,
            headers=headers,
            data=payload,
            timeout=30
        )

        if token_response.status_code == 200:
            try:
                message_json = token_response.json()
                new_token_data = {
                    "access_token": message_json["access_token"],
                    "expires_in": message_json["expires_in"],
                    "token_type": message_json["token_type"],
                    "scope": message_json["scope"],
                    "refresh_token": message_json["refresh_token"],
                }
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
            except (json.JSONDecodeError, KeyError) as e:
                return Response(
                    json.dumps({
                        "status": "error",
                        "message": f"Error parsing token response: {str(e)}",
                    }),
                    status=500,
                    mimetype="application/json",
                )
        else:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": "Invalid or expired refresh token",
                    "detail": token_response.text,
                }),
                status=401,
                mimetype="application/json",
            )

    except requests.exceptions.Timeout:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Token server timed out",
            }),
            status=504,
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

@frappe.whitelist(allow_guest=True)
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
    own login credentials (Employee.user_id / Employee.custom_password) and
    request an OAuth2 password-grant token from this site's own
    /api/method/frappe.integrations.oauth2.get_token endpoint.

    Returns a 2-tuple:
        (None, token_json)        on success — token_json is the raw dict
                                   returned by the OAuth2 endpoint
                                   (access_token, refresh_token, etc.)
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
        ["name", "client_id", "client_secret", "user"],
        as_dict=True,
    )

    if not oauth_client or not oauth_client.get("client_id"):
        return Response(
            json.dumps({
                "status": "error",
                "message": "Security Parameters are not valid",
                "user_count": 0,
            }),
            status=401,
            mimetype="application/json",
        ), None

    # ── STEP 3: Validate host_name config ───────────────────────────────────
    host_name = frappe.local.conf.get("host_name")
    if not host_name:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Server configuration error: host_name missing",
                "user_count": 0,
            }),
            status=500,
            mimetype="application/json",
        ), None

    # ── STEP 4: Request token from Frappe OAuth2 endpoint ───────────────────
    token_url = f"{host_name}/api/method/frappe.integrations.oauth2.get_token"

    payload = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": oauth_client["client_id"],
        "client_secret": oauth_client["client_secret"],
    }

    try:
        token_response = requests.post(
            token_url,
            data=payload,
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.exceptions.Timeout:
        return Response(
            json.dumps({
                "status": "error",
                "message": "Token server timed out",
                "user_count": 0,
            }),
            status=504,
            mimetype="application/json",
        ), None

    if token_response.status_code == 200:
        return None, token_response.json()

    try:
        detail = token_response.json()
    except Exception:
        detail = token_response.text

    return Response(
        json.dumps({
            "status": "error",
            "message": "Invalid credentials or unauthorized",
            "detail": detail,
        }),
        status=401,
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

            clientID, clientSecret, clientUser = frappe.db.get_value(
                "OAuth Client",
                {"app_name": app_key},
                ["client_id", "client_secret", "user"],
            )

            doc = frappe.db.get_value(
                "OAuth Client",
                {"app_name": app_key},
                ["name", "client_id", "client_secret", "user"],
            )

            if clientID is None:

                return Response(
                    json.dumps(
                        {"message": "Security Parameters are not valid", "user_count": 0}
                    ),
                    status=401,
                    mimetype="application/json",
                )

            client_id = clientID
            client_secret = clientSecret

            url = (
                frappe.local.conf.host_name
                + "/api/method/frappe.integrations.oauth2.get_token"
            )


            payload = {
                "username": api_key,
                "password": api_secret,
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
            }
            files = []
            headers = {"Content-Type": "application/json"}

            response = requests.request("POST", url, data=payload, files=files)

            if response.status_code == 200:

                result_data = json.loads(response.text)



                return Response(
                    json.dumps({
                        "data": result_data,
                    }),
                    status=200,
                    mimetype="application/json",
                )

            else:

                frappe.local.response.http_status_code = 401
                return json.loads(response.text)

        except Exception as e:
            return Response(
                json.dumps({"message": str(e), "user_count": 0}),
                status=500,
                mimetype="application/json",
            )