import requests
import json
import frappe

error='Authentication required. Please provide valid credentials..'

@frappe.whitelist(allow_guest=True)
def getToken2(self):
    pass

from frappe.integrations.oauth2 import get_token


@frappe.whitelist(allow_guest=True)
def generate_custom_token(username, password):
    try:
        clientID, clientSecret, clientUser = frappe.db.get_value('OAuth Client', {'app_name': 'MobileAPP'}, ['client_id', 'client_secret','user'])
        client_id = clientID  # Replace with your OAuth client ID
        client_secret = clientSecret  # Replace with your OAuth client secret
        # url = "https://dev.claudion.com/api/method/employee_app.gauth.get_token"
        url =  frappe.local.conf.host_name  + "/api/method/employee_app.gauth.get_token"
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
        if response.status_code == 200:
            return json.loads(response.text)
        else:
            frappe.local.response.http_status_code = 401
            return json.loads(response.text)
            
    except Exception as e:
            frappe.local.response.http_status_code = 401
            return json.loads(response.text)
            
@frappe.whitelist(allow_guest=True)
def generate_custom_token_for_employee( password):
    try:
        clientID, clientSecret, clientUser = frappe.db.get_value('OAuth Client', {'app_name': 'MobileAPP'}, ['client_id', 'client_secret','user'])
        username = clientUser
       
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
            frappe.local.response.http_status_code = 401
            return json.loads(response.text)
        
    except Exception as e:
     
        frappe.local.response.http_status_code = 401
        return json.loads(response.text)

@frappe.whitelist(allow_guest=True)
def whoami():
        try:
            return frappe.session.user
        except Exception as e:
             frappe.throw(error)