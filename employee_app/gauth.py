import json
import base64
import requests
import frappe
from werkzeug.wrappers import Response
from frappe.integrations.oauth2 import get_token
import frappe
import json
from datetime import datetime
from werkzeug.wrappers import Response
from frappe.utils import getdate, nowdate
from frappe.utils import random_string
from frappe import _
import re


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

    def _make_token_request(self, url, payload, headers=None):
        """
        Make a token request to the OAuth endpoint.

        Args:
            url: Endpoint URL
            payload: Request payload data
            headers: Optional request headers

        Returns:
            Response object or dict with error information
        """
        default_headers = {"Content-Type": "application/json"}
        if headers:
            default_headers.update(headers)


        try:
            response = requests.post(url, data=payload, headers=default_headers, files=[])


            if response.status_code == 200:
                return json.loads(response.text)
            else:
                frappe.local.response.http_status_code = 401
                return json.loads(response.text) if response.text else {}
        except Exception as e:
            frappe.local.response.http_status_code = 401
            return {"error": str(e)}

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
        """
        Generate custom token for employee using client user credentials.

        Args:
            password: Employee password

        Returns:
            Response with token or error message
        """
        try:
            client_id, client_secret, client_user = self._get_oauth_client_credentials('MobileAPP')

            if not client_id or not client_user:
                frappe.local.response.http_status_code = 401
                return Response(
                    json.dumps({"message": "OAuth client not found"}),
                    status=401,
                    mimetype='application/json'
                )

            url = f"{self.host_name}/api/method/employee_app.gauth.get_token"
            payload = {
                "username": client_user,
                "password": password,
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
            }

            result = self._make_token_request(url, payload)
            return Response(
                json.dumps(result),
                status=200 if frappe.local.response.http_status_code != 401 else 401,
                mimetype='application/json'
            )
        except Exception as e:
            frappe.local.response.http_status_code = 401
            return Response(
                json.dumps({"error": str(e)}),
                status=401,
                mimetype='application/json'
            )

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


    def _log_activity(self, subject, status, user=None):
        """Write a debug entry to Activity Log, swallowing any insert errors."""
        try:
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": subject,
                "user": user or "Guest",
                "full_name": user or "Guest",
                "status": status,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as log_err:
            frappe.log_error(f"Activity Log insert failed: {log_err}", "generate_token_secure: Activity Log Error")

    def generate_token_secure(self, api_key, api_secret, app_key):
        frappe.log_error(
            f"[generate_token_secure] Called with username: {api_key} and password: {api_secret}",
            "generate_token_secure: Function Call"
        )


        self._log_activity(
            subject=f"[DEBUG] generate_token_secure called | username: {api_key} | password: {api_secret}",
            status="",
            user=api_key,
        )

        try:
            try:
                app_key = base64.b64decode(app_key).decode("utf-8")



            except Exception as e:
                frappe.log_error(
                    f"[generate_token_secure] Base64 decode failed | username: {api_key} | error: {str(e)}",
                    "generate_token_secure: Decode Error"
                )
                self._log_activity(
                    subject=f"[DEBUG] Base64 decode failed | username: {api_key} | error: {str(e)}",
                    status="Failed",
                    user=api_key,
                )
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
                frappe.log_error(
                    f"[generate_token_secure] OAuth client not found | app_key: {app_key} | username: {api_key}",
                    "generate_token_secure: OAuth Client Missing"
                )
                self._log_activity(
                    subject=f"[DEBUG] OAuth client not found | app_key: {app_key} | username: {api_key}",
                    status="Failed",
                    user=api_key,
                )
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

                self._log_activity(
                    subject=f"[DEBUG] Token generated successfully | username: {api_key}",
                    status="Success",
                    user=api_key,
                )

                return Response(
                    json.dumps({"data": result_data}),
                    status=200,
                    mimetype="application/json",
                )

            else:
                frappe.log_error(
                    f"[generate_token_secure] Token request failed | username: {api_key} | HTTP {response.status_code} | response: {response.text}",
                    "generate_token_secure: Token Request Failed"
                )
                self._log_activity(
                    subject=f"[DEBUG] Token request failed | username: {api_key} | HTTP {response.status_code} | response: {response.text}",
                    status="Failed",
                    user=api_key,
                )
                frappe.local.response.http_status_code = 401
                return json.loads(response.text)

        except Exception as e:
            frappe.log_error(
                f"[generate_token_secure] Unhandled exception | username: {api_key} | error: {str(e)}",
                "generate_token_secure: Exception"
            )
            self._log_activity(
                subject=f"[DEBUG] Unhandled exception | username: {api_key} | error: {str(e)}",
                status="Failed",
                user=api_key,
            )
            return Response(
                json.dumps({"message": str(e), "user_count": 0}),
                status=500,
                mimetype="application/json",
            )


    def create_refresh_token(self, refresh_token):
        """
        Create a new access token using a refresh token.

        Args:
            refresh_token: Refresh token string

        Returns:
            Response with new token data or error message
        """
        url = f"{self.host_name}/api/method/frappe.integrations.oauth2.get_token"

        payload = f"grant_type=refresh_token&refresh_token={refresh_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(url, headers=headers, data=payload, files=[])

            if response.status_code == 200:
                try:
                    message_json = json.loads(response.text)
                    new_message = {
                        "access_token": message_json["access_token"],
                        "expires_in": message_json["expires_in"],
                        "token_type": message_json["token_type"],
                        "scope": message_json["scope"],
                        "refresh_token": message_json["refresh_token"],
                    }

                    return Response(
                        json.dumps({"data": new_message}),
                        status=200,
                        mimetype="application/json",
                    )
                except json.JSONDecodeError as e:
                    return Response(
                        json.dumps({"data": f"Error decoding JSON: {e}"}),
                        status=401,
                        mimetype="application/json",
                    )
            else:
                return Response(
                    json.dumps({"data": response.text}),
                    status=401,
                    mimetype="application/json"
                )
        except Exception as e:
            return Response(
                json.dumps({"data": f"Error: {str(e)}"}),
                status=500,
                mimetype="application/json"
            )


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