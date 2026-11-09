import json
import base64
import frappe
from datetime import datetime, timedelta
from werkzeug.wrappers import Response
from frappe.auth import LoginManager
from frappe.utils import getdate, nowdate, now_datetime, flt
from frappe import _
import re
from frappe.utils.password import update_password


def _json(data, status):
    return Response(json.dumps(data), status=status, mimetype="application/json")


def _issue_bearer_token(user, client_name, scopes, expires_in=3600):
    """Create an OAuth Bearer Token in-process (works before and after Frappe 15.122.0)."""
    access_token = frappe.generate_hash(length=30)
    refresh_token = frappe.generate_hash(length=30)
    frappe.get_doc({
        "doctype": "OAuth Bearer Token",
        "client": client_name,
        "user": user,
        "scopes": scopes,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "expiration_time": now_datetime() + timedelta(seconds=expires_in),
        "status": "Active",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh_token,
        "scope": scopes,
    }


def _authenticate(username, password):
    """Validate username/password in-process. Returns the user name or None."""
    try:
        lm = LoginManager()
        lm.authenticate(username, password)
        return lm.user
    except frappe.AuthenticationError:
        frappe.clear_messages()
        return None


class GAuth:
    """Authentication handler for employee app token generation and management."""

    AUTH_ERROR = 'Authentication required. Please provide valid credentials..'

    def __init__(self):
        """Initialize GAuth instance."""
        self.host_name = frappe.local.conf.host_name

    def _get_oauth_client_credentials(self, app_name='MobileAPP'):
        """
        Get OAuth client credentials from database.

        Args:
            app_name: Name of the OAuth client application

        Returns:
            tuple: (client_id, client_secret, client_user) or (None, None, None) if not found
        """
        try:
            credentials = frappe.db.get_value(
                'OAuth Client',
                {'app_name': app_name},
                ['client_id', 'client_secret', 'user']
            )
            if credentials:
                return credentials
            return (None, None, None)
        except Exception:
            return (None, None, None)

    def get_token2(self):
        """Placeholder method for token generation."""
        pass

    def generate_custom_token(self, username, password):
        """
        Generate custom token for a user (development/testing only).

        Args:
            username: User username
            password: User password

        Returns:
            Response with token or error message
        """
        # This function can be used for development testing only. not for production.
        return Response(
            json.dumps({
                "message": "Can not be used for production environmet",
                "user_count": 0
            }),
            status=500,
            mimetype='application/json'
        )

        # Uncomment below for development use
        # try:
        #     client_id, client_secret, client_user = self._get_oauth_client_credentials('MobileAPP')
        #
        #     if not client_id:
        #         frappe.local.response.http_status_code = 401
        #         return Response(
        #             json.dumps({"message": "OAuth client not found"}),
        #             status=401,
        #             mimetype='application/json'
        #         )
        #
        #     url = f"{self.host_name}/api/method/employee_app.gauth.get_token"
        #     payload = {
        #         "username": username,
        #         "password": password,
        #         "grant_type": "password",
        #         "client_id": client_id,
        #         "client_secret": client_secret,
        #     }
        #
        #     result = self._make_token_request(url, payload)
        #     return Response(
        #         json.dumps(result),
        #         status=200 if frappe.local.response.http_status_code != 401 else 401,
        #         mimetype='application/json'
        #     )
        # except Exception as e:
        #     frappe.local.response.http_status_code = 401
        #     return Response(
        #         json.dumps({"error": str(e)}),
        #         status=401,
        #         mimetype='application/json'
        #     )

    def generate_custom_token_for_employee(self, password):
        """Generate token for the MobileAPP OAuth client's user."""
        client = frappe.db.get_value(
            "OAuth Client", {"app_name": "MobileAPP"}, ["name", "scopes", "user"], as_dict=True
        )
        if not client or not client.user:
            return _json({"message": "OAuth client not found"}, 401)

        user = _authenticate(client.user, password)
        if not user:
            return _json({"error": "invalid_grant", "error_description": "Invalid credentials given."}, 401)

        return _json(_issue_bearer_token(user, client.name, client.scopes), 200)

    def whoami(self):
        """
        Get current session user.

        Returns:
            Current session username or raises error
        """
        try:
            return frappe.session.user
        except Exception as e:
            frappe.throw(self.AUTH_ERROR)


    def generate_token_secure(self, api_key, api_secret, app_key):
        """Username/password login. Works before and after Frappe 15.122.0."""
        # Only plain strings: other JSON types would reach the user lookup as filter operators.
        if not all(isinstance(value, str) for value in (api_key, api_secret, app_key)):
            return _json({"error": "invalid_grant", "error_description": "Invalid credentials given."}, 401)
        try:
            app_name = base64.b64decode(app_key).decode("utf-8")
        except Exception:
            return _json({"message": "Security Parameters are not valid", "user_count": 0}, 401)

        client = frappe.db.get_value(
            "OAuth Client", {"app_name": app_name}, ["name", "scopes"], as_dict=True
        )
        if not client:
            return _json({"message": "Security Parameters are not valid", "user_count": 0}, 401)

        user = _authenticate(api_key, api_secret)
        if not user:
            return _json({"error": "invalid_grant", "error_description": "Invalid credentials given."}, 401)

        try:
            return _json({"data": _issue_bearer_token(user, client.name, client.scopes)}, 200)
        except Exception as e:
            frappe.log_error(title="generate_token_secure: token insert failed", message=str(e))
            return _json({"message": "Could not issue token", "user_count": 0}, 500)

    def create_refresh_token(self, refresh_token):
        """Swap a refresh token for a new pair, once (auth_core.rotate_refresh_token)."""
        from employee_app.auth_core import log_failure, rotate_refresh_token

        try:
            token = rotate_refresh_token(refresh_token)
        except Exception:
            return _json({"data": "Error", "ref": log_failure("create_refresh_token")}, 500)
        if not token:
            return _json({"data": "invalid_grant"}, 401)
        return _json({"data": token}, 200)


# Create a singleton instance
_gauth_instance = GAuth()


# Expose methods as module-level functions for Frappe whitelist decorator
@frappe.whitelist()
def getToken2():
    """Get token method (placeholder)."""
    return _gauth_instance.get_token2()


@frappe.whitelist()
def generate_custom_token(username, password):
    """Generate custom token for a user."""
    return _gauth_instance.generate_custom_token(username, password)


@frappe.whitelist()
def generate_custom_token_for_employee(password):
    """Generate custom token for employee."""
    return _gauth_instance.generate_custom_token_for_employee(password)


@frappe.whitelist()
def whoami():
    """Get current session user."""
    return _gauth_instance.whoami()


@frappe.whitelist(allow_guest=True)
def generate_token_secure(api_key, api_secret, app_key):

    """Generate token with secure parameters."""
    return _gauth_instance.generate_token_secure(api_key, api_secret, app_key)





@frappe.whitelist(allow_guest=True)
def create_refresh_token(refresh_token):
    """Create a new access token using refresh token."""
    return _gauth_instance.create_refresh_token(refresh_token)



@frappe.whitelist(allow_guest=False)
def create_attendence_request(employee, from_date, to_date,from_time,to_time,reason):
    try:
        today = getdate(nowdate())
        from_date_obj = getdate(from_date)
        to_date_obj = getdate(to_date)


        if from_date_obj > today or to_date_obj > today:
            return Response(
                json.dumps({"message": "Future dates are not allowed. Please select current or previous dates."}),
                status=400,
                mimetype="application/json"
            )


        if from_date_obj > to_date_obj:
            return Response(
                json.dumps({"message": "From Date cannot be greater than To Date."}),
                status=400,
                mimetype="application/json"
            )


        doc = frappe.get_doc({
            "doctype": "Attendance Request",
            "employee": employee,
            "from_date": from_date,
            "to_date": to_date,
            "custom_from_time": from_time,
            "custom_to_time": to_time,
            "reason": reason
        })
        doc.insert()

        data = {
            "name": doc.name,
            "employee": doc.employee,
            "from_date": str(doc.from_date),
            "to_date": str(doc.to_date),
            "from_time": doc.custom_from_time,
            "to_time": doc.custom_to_time,
            "reason": doc.reason,
        }

        return Response(
            json.dumps({"message": data}),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps({"message": f"Error creating attendance request: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )



@frappe.whitelist(allow_guest=False)
def validate_location_restriction(employee, latitude, longitude):
    try:
        # Placeholder for actual location validation logic
        # You can implement geofencing or other location-based checks here

        # For demonstration, let's assume the location is valid if latitude and longitude are within certain bounds
        if 10.0 <= latitude <= 50.0 and 60.0 <= longitude <= 100.0:
            return Response(
                json.dumps({"message": "Location is valid."}),
                status=200,
                mimetype="application/json"
            )
        else:
            return Response(
                json.dumps({"message": "Location is invalid."}),
                status=400,
                mimetype="application/json"
            )

    except Exception as e:
        return Response(
            json.dumps({"message": f"Error validating location: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )



def validate_location_restriction(doc, method):
    if doc.custom_restrict_location:
        if not doc.custom_employee_location1 or len(doc.custom_employee_location1) == 0:
            frappe.throw(_("Please add at least one location when 'Restrict Location' is enabled."))




def validate_coordinates(doc, method=None):

    decimal_pattern = r"^-?\d+(\.\d+)?$"

    lat = doc.lat
    lng = doc.long


    if (lat and not lng) or (lng and not lat):
        frappe.throw(_("Both Latitude and Longitude are required together."))


    if lat not in [None, ""]:
        lat_str = str(lat).strip()

        if not re.match(decimal_pattern, lat_str):
            frappe.throw(
                _("Latitude format is invalid. Use decimal format only (example: 11.532393).")
            )

        lat_value = float(lat_str)

        if lat_value < -90 or lat_value > 90:
            frappe.throw(
                _("Latitude must be between -90 and 90.")
            )


    if lng not in [None, ""]:
        lng_str = str(lng).strip()

        if not re.match(decimal_pattern, lng_str):
            frappe.throw(
                _("Longitude format is invalid. Use decimal format only (example: 75.615743).")
            )

        lng_value = float(lng_str)

        if lng_value < -180 or lng_value > 180:
            frappe.throw(
                _("Longitude must be between -180 and 180.")
            )






@frappe.whitelist()
def get_tasks(id=None):
    if id:
        todo = frappe.get_doc("ToDo", id)

        return {
            "id": todo.name,
            "name": todo.name,
            "status": map_status(todo.status),
            "priority": map_priority(todo.priority),
            "category": "",
            "type": "other",
            "location": {
                "tower": "",
                "floor": "",
                "room": ""
            },
            "reportedBy": {
                "id": todo.owner,
                "name": frappe.db.get_value(
                    "User", todo.owner, "full_name"
                ) or todo.owner
            },
            "reportedOn": todo.creation,
            "progress": 100 if todo.status == "Closed" else 0,
            "assignedTo": {
                "id": todo.allocated_to or "",
                "name": frappe.db.get_value(
                    "User",
                    todo.allocated_to,
                    "full_name"
                ) if todo.allocated_to else "",
                "team": ""
            },
            "dueDate": todo.date,
            "description": todo.description
        }

    todos = frappe.get_all(
        "ToDo",
        fields=[
            "name",
            "description",
            "status",
            "priority",
            "date"
        ]
    )

    return {
        "tasks": [
            {
                "id": d.name,
                "name": d.name,
                "status": map_status(d.status),
                "priority": map_priority(d.priority),
                "dueDate": d.date
            }
            for d in todos
        ]
    }


def map_status(status):
    status_map = {
        "Open": "open",
        "Closed": "completed",
        "Cancelled": "cancelled"
    }
    return status_map.get(status, "in_progress")


def map_priority(priority):
    priority_map = {
        "Low": "low",
        "Medium": "medium",
        "High": "high"
    }
    return priority_map.get(priority, "medium")


@frappe.whitelist()
def salary_advance_request(employee,amount,date,reason):

    try:
        amount = flt(amount)
        company = frappe.db.get_value("Employee", employee, "company")
        currency = "SAR"
        company_currency = frappe.get_cached_value("Company", company, "default_currency")

        if currency == company_currency:
            exchange_rate = 1.0
        else:
            from erpnext.setup.utils import get_exchange_rate
            exchange_rate = get_exchange_rate(currency, company_currency)

        gross_salary = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": employee, "docstatus": 1, "from_date": ["<=", date]},
            "base",
            order_by="from_date desc"
        )

        doc = frappe.get_doc({
            "doctype": "Employee Advance",
            "employee": employee,
            "company": company,
            "advance_amount": amount,
            "purpose": reason,
            "currency": currency,
            "exchange_rate": exchange_rate,
            "posting_date": date,
            "custom_salary": gross_salary or 0
        })
        doc.insert()


        data = {
            "name": doc.name,
            "employee": doc.employee,
            "advance_amount": doc.advance_amount,
            "purpose": doc.purpose,
            "posting_date": str(doc.posting_date),
            "currency": doc.currency,
            "custom_salary": doc.custom_salary
        }

        return Response(
            json.dumps(data),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps({"message": f"Error creating salary advance request: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )


@frappe.whitelist()
def create_overtime_request(employee, date,overtime_hours=None, from_time=None, to_time=None,reason=None):
    try:
        doc = frappe.get_doc({
            "doctype": "Overtime Request",
            "employee": employee,
            "date": date,
            "from_time": from_time,
            "to_time": to_time,
            "reason": reason,
            "overtime_hour": overtime_hours
        })
        doc.insert()

        data = {
            "name": doc.name,
            "employee": doc.employee,
            "date": str(doc.date),
            "from_time": str(doc.from_time),
            "to_time": str(doc.to_time),
            "reason": doc.reason,
            "overtime_hours": int(doc.overtime_hour) if doc.overtime_hour is not None else 0
        }

        return Response(
            json.dumps(data),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps({"message": f"Error creating overtime request: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )

@frappe.whitelist()
def get_employee_overtime_requests(employee,date=None):
    try:
        overtime_requests = frappe.get_all(
            "Overtime Request",
            filters={"employee": employee, "date": date} if date else {"employee": employee},
            fields=["name", "date", "from_time", "to_time", "reason", "status"]
        )

        data = [
            {
                "name": req.name,
                "date": str(req.date),
                "from_time": str(req.from_time),
                "to_time": str(req.to_time),
                "reason": req.reason,
                "status": req.status
            }
            for req in overtime_requests
        ]

        return Response(
            json.dumps(data),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps({"message": f"Error fetching overtime requests: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )



@frappe.whitelist(methods=["POST"])
def create_new_password(mobile_no=None, otp=None, new_password=None):
    """
    Set the login password of the Employee matched exactly by mobile_no,
    after the OTP sent by authentication.generate_and_send_otp(mobile_no).

    Allowed only while one of the setup rules holds for that employee at this
    moment, as get_employee_login_policy reports them: password_setup_allowed
    (otp_verified_password_setup, the mobile app) or erp_password_setup_allowed
    (erp_web_password_setup_allowed, OTP-only employees' ERP password). The
    password is the employee's ERP website password too. The employee's
    Authentication policy never changes here; their other sessions end.
    Replies are nested under "data" (frozen contract).
    """
    from employee_app.auth_core import (
        TOO_MANY,
        auth_event,
        erp_password_setup_allowed,
        find_employee,
        log_failure,
        password_setup_allowed,
        password_too_weak,
        revoke_tokens,
        throttle_ip,
        verify_otp,
    )
    from employee_app.authentication import _update_user_created_password_flag, is_placeholder_password

    def refuse(message, status):
        return _json({"data": {"status": "error", "message": message}}, status)

    try:
        throttle_ip("set_password")

        if not mobile_no or not otp or not new_password or not isinstance(new_password, str):
            return refuse("mobile_no, otp and new_password are required", 400)

        if is_placeholder_password(new_password):
            return refuse("Please choose a different password", 400)

        found = find_employee(mobile_no)
        if not found or not found.user_id:
            return refuse("No employee user found for the given phone number", 404)

        # Row lock until commit: one setup per employee at a time, and the rule
        # below reads current data.
        employee = frappe.get_doc("Employee", found.name, for_update=True)
        if not (password_setup_allowed(employee) or erp_password_setup_allowed(employee)):
            return refuse("Password setup is not available", 403)

        # Frappe's password policy, when the site enables it. Reuses the message the app already maps.
        if password_too_weak(employee.user_id, new_password):
            return refuse("Please choose a different password", 400)

        # The OTP is spent only once everything else has passed.
        if not verify_otp(employee.name, otp):
            return refuse("Invalid or expired OTP", 401)

        # Other writes first: update_password commits when it ends Desk sessions.
        revoke_tokens(employee.user_id)
        _update_user_created_password_flag(employee.name, new_password)
        update_password(employee.user_id, new_password, logout_all_sessions=True)
        auth_event("password_set", employee.name)

        return _json({"data": {
            "status": "success",
            "message": "Password updated successfully",
            "employee_id": employee.name,
        }}, 200)

    except frappe.RateLimitExceededError:
        return refuse(TOO_MANY, 429)
    except Exception:
        return _json({"data": {
            "status": "error",
            "message": "Something went wrong",
            "ref": log_failure("create_new_password"),
        }}, 500)

GEO_TAGGING_OPTIONS = {
    "Disable geotagging": 0,
    "Enable geotagging for warnings only": 1,
    "Enable geotagging for all attendance actions": 2,
}


@frappe.whitelist()
def employee_checkin_setting():
    try:
        settings = frappe.get_doc("Checkin App Setting")
        data = {
            "attendance_action": {
                "offline_attendance": bool(settings.offline_attendance),
                "photo_upload": bool(settings.photo_upload),
                "restrict_location": bool(settings.restrict_location),
                "unrestricted_checkout_location": bool(settings.unrestricted_checkout_location),
                "employee_shift": bool(settings.employee_shift),
                "geo_tagging": bool(settings.geo_tagging),
                "employee_checkin_break": bool(settings.employee_checkin_break),
                "attendance_request": bool(settings.attendance_request),
                "attendance_history": bool(settings.attendance_history)
            },
            "loan_application": bool(settings.loan_application),
            "expense_claim": bool(settings.expense_claim),
            "leave_request": bool(settings.leave_request),
            "employee_records": bool(settings.employee_records),
            "complaints": bool(settings.complaints),
            "employee_resignation": bool(settings.employee_resignation),
        }
        return Response(
            json.dumps(data),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        return Response(
            json.dumps({"message": f"Error fetching employee checkin settings: {str(e)}"}),
            status=500,
            mimetype="application/json"
        )