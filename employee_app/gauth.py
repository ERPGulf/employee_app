import requests
import json
import frappe

error='Authentication required. Please provide valid credentials..'
@frappe.whitelist(allow_guest=True)
def getToken(self):
    try:
        if not username or not password:
             frappe.throw(error)

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
             frappe.throw(error)
            # Failed login
            
    except Exception as e:
         frappe.throw(error)


from frappe.integrations.oauth2 import get_token


@frappe.whitelist(allow_guest=True)
def generate_custom_token(username, password):
    try:
        clientID, clientSecret, clientUser = frappe.db.get_value('OAuth Client', {'app_name': 'MobileAPP'}, ['client_id', 'client_secret','user'])
        # return str(clientID) + " "  + str(clientSecret) +  " "  +  str(clientUser)
        if not username or not password:
           frappe.throw(error)
        # so basically we are going to use inbuilt frappe oauth2 and generate token from it by passing creds
        # Use Frappe's oauth2.grant_password function to generate tokens
        client_id = clientID  # Replace with your OAuth client ID
        client_secret = clientSecret  # Replace with your OAuth client secret
        # url = "https://dev.claudion.com/api/method/employee_app.gauth.get_token"
        url =  frappe.local.conf.host_name  + "/api/method/employee_app.gauth.get_token"
        # url =  frappe.local.conf.host_name  + "api/method/employee_app.attendance_api.vehicle_list"
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
        # return json.loads(response.text)
        if response.status_code == 200:
            return json.loads(response.text)
        else:
             frappe.throw(error)

    except Exception as e:
              frappe.throw(error)
         
@frappe.whitelist(allow_guest=True)
def generate_custom_token_for_employee( password):
    try:
        clientID, clientSecret, clientUser = frappe.db.get_value('OAuth Client', {'app_name': 'MobileAPP'}, ['client_id', 'client_secret','user'])
        # return str(clientID) + " "  + str(clientSecret) +  " "  +  str(clientUser)
        username = clientUser
        if not username or not password:
            # frappe.throw("Username and password are required.")
               frappe.throw(error)
        # so basically we are going to use inbuilt frappe oauth2 and generate token from it by passing creds
        # Use Frappe's oauth2.grant_password function to generate tokens
        client_id = clientID  # Replace with your OAuth client ID
        client_secret = clientSecret  # Replace with your OAuth client secret
        # url = "https://dev.claudion.com/api/method/employee_app.gauth.get_token"
        url =  frappe.local.conf.host_name  + "/api/method/employee_app.gauth.get_token"
        payload = {
            # "username": username,
            "username": clientUser,
            "password": password,
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        files = []
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", url, data=payload, files=files)
        # return json.loads(response.text)
        if response.status_code == 200:
            return json.loads(response.text)
        else:
            frappe.throw(error)

    except Exception as e:
     
         frappe.throw(error)


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
         frappe.throw(error)


@frappe.whitelist(allow_guest=True)
def get_all_users():
    try:
        # Get all users
        users = frappe.get_all("User", fields="*", filters={"enabled": 1})

        # Return the list of users as JSON
        return {"users": users}
    except Exception as e:
        frappe.throw(error)

#check who is logged in
@frappe.whitelist(allow_guest=True)
def whoami():
        try:
            return frappe.session.user
        except Exception as e:
             frappe.throw(error)