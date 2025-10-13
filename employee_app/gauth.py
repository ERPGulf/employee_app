import requests
import json
import frappe
from werkzeug.wrappers import Response
import requests
import json
import frappe
import json
import urllib.parse;
import base64
from frappe.utils.image import optimize_image
import os
from frappe.utils import cint
from mimetypes import guess_type
from typing import TYPE_CHECKING
from werkzeug.wrappers import Response

error='Authentication required. Please provide valid credentials..'

@frappe.whitelist(allow_guest=True)
def getToken2(self):
    pass

from frappe.integrations.oauth2 import get_token


@frappe.whitelist(allow_guest=True)
def generate_custom_token(username, password):

    #this function can be used for development testing only. not for production. Uncomment the below code to use it.
    return Response(json.dumps({"message": "Can not be used for production environmet" , "user_count": 0}), status=500, mimetype='application/json')
    #------------

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
    # return "hello"
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



@frappe.whitelist(allow_guest=True)
def generate_token_secure( api_key, api_secret, app_key):

    try:
        try:
            app_key = base64.b64decode(app_key).decode("utf-8")

        except Exception as e:
            return Response(json.dumps({"message": "Security Parameters are not valid" , "user_count": 0}), status=401, mimetype='application/json')
        clientID, clientSecret, clientUser = frappe.db.get_value('OAuth Client', {'app_name': app_key}, ['client_id', 'client_secret','user'])

        if clientID is None:
            # return app_key
            return Response(json.dumps({"message": "Security Parameters are not valid" , "user_count": 0}), status=401, mimetype='application/json')

        client_id = clientID  # Replace with your OAuth client ID
        client_secret = clientSecret  # Replace with your OAuth client secret
        url =  frappe.local.conf.host_name  + "/api/method/frappe.integrations.oauth2.get_token"
        payload = {
            "username": api_key,
            "password": api_secret,
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            # "grant_type": "refresh_token"
        }
        files = []
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", url, data=payload, files=files)
        if response.status_code == 200:
            result_data = json.loads(response.text)
            return Response(json.dumps({"data":result_data}), status=200, mimetype='application/json')

        else:
            frappe.local.response.http_status_code = 401
            return json.loads(response.text)

    except Exception as e:
            # frappe.local.response.http_status_code = 401
            # return json.loads(response.text)
            return Response(json.dumps({"message": e , "user_count": 0}), status=500, mimetype='application/json')




@frappe.whitelist(allow_guest=True)
def create_refresh_token(refresh_token):
    url = (
        frappe.local.conf.host_name + "/api/method/frappe.integrations.oauth2.get_token"
    )

    payload = f"grant_type=refresh_token&refresh_token={refresh_token}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    files = []
    response = requests.post(url, headers=headers, data=payload, files=files)

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
            json.dumps({"data": response.text}), status=401, mimetype="application/json"
        )