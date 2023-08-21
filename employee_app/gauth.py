import requests
import json
import frappe


def getToken(self):
    try:
        if not username or not password:
            frappe.throw("Username and password are required.")

        # Authenticate user credentials
        user = frappe.get_doc("User", {"email": username})
        if user and frappe.utils.password.check_password(user.password, password):
            # Successful login, generate access token
            token = frappe.generate_hash(length=40)  # Generate a random access token
            frappe.cache().hset(
                "user_tokens", token, user.name
            )  # Store the token in Redis cache
            return {"access_token": token}
        else:
            # Failed login
            frappe.throw("Invalid login credentials.")
    except Exception as e:
        frappe.throw("An error occurred during login.")


from frappe.integrations.oauth2 import get_token


@frappe.whitelist(allow_guest=True)
def generate_custom_token(username, password):
    try:
        if not username or not password:
            frappe.throw("Username and password are required.")
        # so basically we are going to use inbuilt frappe oauth2 and generate token from it by passing creds
        # Use Frappe's oauth2.grant_password function to generate tokens
        client_id = "fa3c840500"  # Replace with your OAuth client ID
        client_secret = "718cfef464"  # Replace with your OAuth client secret
        url = "https://dev.claudion.com/api/method/employee_app.gauth.get_token"
        payload = {
            "username": username,
            "password": password,
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        files = []
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", url, data=payload, files=files)
        return json.loads(response.text)

    except Exception as e:
        frappe.throw("An error occurred during login.")


from frappe.auth import LoginManager


@frappe.whitelist(allow_guest=True)
def generate_access_token(username, password):
    # from frappe.utils.password import check_password
    try:
        # if not username or not password:
        # 	frappe.throw("Username and password are required.")

        # Authenticate user credentials
        login_manager = LoginManager()
        user = login_manager.authenticateCustom(user=username, pwd=password)

        response_data = {"access_token": frappe.session.sid, "user": user}
        frappe.response["message"] = response_data
        # else:
        # Failed login
        #    return {"error": "Invalid login credentials."}
    except Exception as e:
        frappe.throw("An error occurred during login.")


@frappe.whitelist(allow_guest=True)
def get_all_users():
    try:
        # Get all users
        users = frappe.get_all("User", fields="*", filters={"enabled": 1})

        # Return the list of users as JSON
        return {"users": users}
    except Exception as e:
        frappe.throw("An error occurred while fetching users.")
