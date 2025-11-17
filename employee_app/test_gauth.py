# Copyright (c) 2025, ERPGulf.com and Contributors
# See license.txt

import json
import base64
from unittest.mock import Mock, patch, MagicMock
import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.wrappers import Response
import requests

from employee_app.gauth import GAuth


class TestGAuth(FrappeTestCase):
    """Test cases for GAuth class."""

    def setUp(self):
        """Set up test fixtures."""
        self.gauth = GAuth()
        self.gauth.host_name = "https://test.example.com"
        
        # Sample OAuth credentials
        self.client_id = "test_client_id"
        self.client_secret = "test_client_secret"
        self.client_user = "test_user@example.com"
        
        # Sample token response
        self.token_response = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "read write"
        }

    def tearDown(self):
        """Clean up after tests."""
        pass

    @patch('employee_app.gauth.frappe.db.get_value')
    def test_get_oauth_client_credentials_success(self, mock_get_value):
        """Test successful retrieval of OAuth client credentials."""
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        
        result = self.gauth._get_oauth_client_credentials('MobileAPP')
        
        self.assertEqual(result, (self.client_id, self.client_secret, self.client_user))
        mock_get_value.assert_called_once_with(
            'OAuth Client',
            {'app_name': 'MobileAPP'},
            ['client_id', 'client_secret', 'user']
        )

    @patch('employee_app.gauth.frappe.db.get_value')
    def test_get_oauth_client_credentials_not_found(self, mock_get_value):
        """Test when OAuth client credentials are not found."""
        mock_get_value.return_value = None
        
        result = self.gauth._get_oauth_client_credentials('NonExistentApp')
        
        self.assertEqual(result, (None, None, None))

    @patch('employee_app.gauth.frappe.db.get_value')
    def test_get_oauth_client_credentials_exception(self, mock_get_value):
        """Test exception handling in _get_oauth_client_credentials."""
        mock_get_value.side_effect = Exception("Database error")
        
        result = self.gauth._get_oauth_client_credentials('MobileAPP')
        
        self.assertEqual(result, (None, None, None))

    @patch('employee_app.gauth.requests.post')
    @patch('employee_app.gauth.frappe.local.response')
    def test_make_token_request_success(self, mock_response, mock_post):
        """Test successful token request."""
        mock_response_obj = Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.text = json.dumps(self.token_response)
        mock_post.return_value = mock_response_obj
        
        url = "https://test.example.com/api/method/test"
        payload = {"grant_type": "password"}
        
        result = self.gauth._make_token_request(url, payload)
        
        self.assertEqual(result, self.token_response)
        mock_post.assert_called_once()

    @patch('employee_app.gauth.requests.post')
    @patch('employee_app.gauth.frappe.local.response')
    def test_make_token_request_failure(self, mock_response, mock_post):
        """Test failed token request."""
        mock_response_obj = Mock()
        mock_response_obj.status_code = 401
        mock_response_obj.text = json.dumps({"error": "Unauthorized"})
        mock_post.return_value = mock_response_obj
        
        url = "https://test.example.com/api/method/test"
        payload = {"grant_type": "password"}
        
        result = self.gauth._make_token_request(url, payload)
        
        self.assertEqual(result, {"error": "Unauthorized"})
        self.assertEqual(mock_response.http_status_code, 401)

    @patch('employee_app.gauth.requests.post')
    @patch('employee_app.gauth.frappe.local.response')
    def test_make_token_request_exception(self, mock_response, mock_post):
        """Test exception handling in token request."""
        mock_post.side_effect = Exception("Network error")
        
        url = "https://test.example.com/api/method/test"
        payload = {"grant_type": "password"}
        
        result = self.gauth._make_token_request(url, payload)
        
        self.assertIn("error", result)
        self.assertEqual(mock_response.http_status_code, 401)

    def test_get_token2(self):
        """Test get_token2 placeholder method."""
        result = self.gauth.get_token2()
        self.assertIsNone(result)

    def test_generate_custom_token_production_block(self):
        """Test that generate_custom_token blocks production use."""
        result = self.gauth.generate_custom_token("testuser", "testpass")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["message"], "Can not be used for production environmet")
        self.assertEqual(result.status_code, 500)

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch.object(GAuth, '_make_token_request')
    @patch('employee_app.gauth.frappe.local.response')
    def test_generate_custom_token_for_employee_success(self, mock_response, mock_token_request, mock_get_value):
        """Test successful employee token generation."""
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        mock_response.http_status_code = 200
        mock_token_request.return_value = self.token_response
        
        result = self.gauth.generate_custom_token_for_employee("test_password")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data, self.token_response)
        self.assertEqual(result.status_code, 200)

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch('employee_app.gauth.frappe.local.response')
    def test_generate_custom_token_for_employee_no_credentials(self, mock_response, mock_get_value):
        """Test employee token generation when credentials are not found."""
        mock_get_value.return_value = (None, None, None)
        mock_response.http_status_code = 401
        
        result = self.gauth.generate_custom_token_for_employee("test_password")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["message"], "OAuth client not found")
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch.object(GAuth, '_make_token_request')
    @patch('employee_app.gauth.frappe.local.response')
    def test_generate_custom_token_for_employee_exception(self, mock_response, mock_token_request, mock_get_value):
        """Test exception handling in employee token generation."""
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        mock_token_request.side_effect = Exception("Request failed")
        mock_response.http_status_code = 401
        
        result = self.gauth.generate_custom_token_for_employee("test_password")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertIn("error", response_data)
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.frappe.session')
    def test_whoami_success(self, mock_session):
        """Test successful whoami call."""
        mock_session.user = "test@example.com"
        
        result = self.gauth.whoami()
        
        self.assertEqual(result, "test@example.com")

    @patch('employee_app.gauth.frappe.session')
    @patch('employee_app.gauth.frappe.throw')
    def test_whoami_exception(self, mock_throw, mock_session):
        """Test whoami when session is not available."""
        # Simulate session access failure
        mock_throw.side_effect = Exception("Frappe throw called")
        mock_session.user = Mock(side_effect=AttributeError("No user"))
        
        with self.assertRaises(Exception) as context:
            self.gauth.whoami()
        
        # Verify frappe.throw was called with the error message
        mock_throw.assert_called_once_with(GAuth.AUTH_ERROR)
        self.assertEqual(str(context.exception), "Frappe throw called")

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch.object(GAuth, '_make_token_request')
    @patch('employee_app.gauth.frappe.local.response')
    def test_generate_token_secure_success(self, mock_response, mock_token_request, mock_get_value):
        """Test successful secure token generation."""
        app_key_encoded = base64.b64encode("MobileAPP".encode()).decode()
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        mock_response.http_status_code = 200
        mock_token_request.return_value = self.token_response
        
        result = self.gauth.generate_token_secure("api_key", "api_secret", app_key_encoded)
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["data"], self.token_response)
        self.assertEqual(result.status_code, 200)

    def test_generate_token_secure_invalid_base64(self):
        """Test secure token generation with invalid base64 app key."""
        result = self.gauth.generate_token_secure("api_key", "api_secret", "invalid_base64!")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["message"], "Security Parameters are not valid")
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.frappe.db.get_value')
    def test_generate_token_secure_no_client(self, mock_get_value):
        """Test secure token generation when OAuth client is not found."""
        app_key_encoded = base64.b64encode("MobileAPP".encode()).decode()
        mock_get_value.return_value = (None, None, None)
        
        result = self.gauth.generate_token_secure("api_key", "api_secret", app_key_encoded)
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["message"], "Security Parameters are not valid")
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch.object(GAuth, '_make_token_request')
    @patch('employee_app.gauth.frappe.local.response')
    def test_generate_token_secure_request_failure(self, mock_response, mock_token_request, mock_get_value):
        """Test secure token generation when request fails."""
        app_key_encoded = base64.b64encode("MobileAPP".encode()).decode()
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        mock_response.http_status_code = 401
        mock_token_request.return_value = {"error": "Unauthorized"}
        
        result = self.gauth.generate_token_secure("api_key", "api_secret", app_key_encoded)
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data, {"error": "Unauthorized"})
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.frappe.db.get_value')
    @patch.object(GAuth, '_make_token_request')
    def test_generate_token_secure_exception(self, mock_token_request, mock_get_value):
        """Test exception handling in secure token generation."""
        app_key_encoded = base64.b64encode("MobileAPP".encode()).decode()
        mock_get_value.return_value = (self.client_id, self.client_secret, self.client_user)
        mock_token_request.side_effect = Exception("Unexpected error")
        
        result = self.gauth.generate_token_secure("api_key", "api_secret", app_key_encoded)
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertIn("message", response_data)
        self.assertEqual(result.status_code, 500)

    @patch('employee_app.gauth.requests.post')
    def test_create_refresh_token_success(self, mock_post):
        """Test successful refresh token creation."""
        mock_response_obj = Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.text = json.dumps(self.token_response)
        mock_post.return_value = mock_response_obj
        
        result = self.gauth.create_refresh_token("test_refresh_token")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["data"]["access_token"], self.token_response["access_token"])
        self.assertEqual(response_data["data"]["refresh_token"], self.token_response["refresh_token"])
        self.assertEqual(result.status_code, 200)

    @patch('employee_app.gauth.requests.post')
    def test_create_refresh_token_invalid_json(self, mock_post):
        """Test refresh token creation with invalid JSON response."""
        mock_response_obj = Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.text = "invalid json"
        mock_post.return_value = mock_response_obj
        
        result = self.gauth.create_refresh_token("test_refresh_token")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertIn("Error decoding JSON", response_data["data"])
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.requests.post')
    def test_create_refresh_token_failure(self, mock_post):
        """Test refresh token creation when request fails."""
        mock_response_obj = Mock()
        mock_response_obj.status_code = 401
        mock_response_obj.text = "Unauthorized"
        mock_post.return_value = mock_response_obj
        
        result = self.gauth.create_refresh_token("test_refresh_token")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertEqual(response_data["data"], "Unauthorized")
        self.assertEqual(result.status_code, 401)

    @patch('employee_app.gauth.requests.post')
    def test_create_refresh_token_exception(self, mock_post):
        """Test exception handling in refresh token creation."""
        mock_post.side_effect = Exception("Network error")
        
        result = self.gauth.create_refresh_token("test_refresh_token")
        
        self.assertIsInstance(result, Response)
        response_data = json.loads(result.data.decode())
        self.assertIn("Error", response_data["data"])
        self.assertEqual(result.status_code, 500)

    def test_make_token_request_with_custom_headers(self):
        """Test token request with custom headers."""
        custom_headers = {"Authorization": "Bearer token"}
        
        with patch('employee_app.gauth.requests.post') as mock_post, \
             patch('employee_app.gauth.frappe.local.response') as mock_response:
            mock_response_obj = Mock()
            mock_response_obj.status_code = 200
            mock_response_obj.text = json.dumps(self.token_response)
            mock_post.return_value = mock_response_obj
            
            url = "https://test.example.com/api/method/test"
            payload = {"grant_type": "password"}
            
            self.gauth._make_token_request(url, payload, headers=custom_headers)
            
            # Verify headers were merged correctly
            call_args = mock_post.call_args
            headers = call_args[1]['headers']
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(headers["Authorization"], "Bearer token")

