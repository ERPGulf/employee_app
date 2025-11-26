import json
import base64
import requests
import frappe
from werkzeug.wrappers import Response
from frappe.integrations.oauth2 import get_token


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


    def generate_token_secure(self,api_key, api_secret, app_key):

        try:
            try:
                app_key = base64.b64decode(app_key).decode("utf-8")

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
                # return app_key
                return Response(
                    json.dumps(
                        {"message": "Security Parameters are not valid", "user_count": 0}
                    ),
                    status=401,
                    mimetype="application/json",
                )

            client_id = clientID  # Replace with your OAuth client ID
            client_secret = clientSecret  # Replace with your OAuth client secret

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
                    json.dumps({"data": result_data}),
                    status=200,
                    mimetype="application/json",
                )

            else:

                frappe.local.response.http_status_code = 401
                return json.loads(response.text)

        except Exception as e:

            return Response(
                json.dumps({"message": e, "user_count": 0}),
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