# Mobile authentication API contract

This is the contract the mobile auth SDK (0.1.x and 0.2.0) depends on.

- **Don't change a live reply in place.** Add a new endpoint instead, and send the SDK team a sanitized example before changing any message, status, nesting or key below.
- **Tests guard it:** `employee_app/tests/test_auth_remediation.py`.
- **Implementation:** shared checks in `employee_app/auth_core.py`; the endpoints are in `authentication.py`, `sign_in.py` and `gauth.py`.

## Endpoints

All are `/api/method/<path>`. Form-encoded or JSON bodies are accepted unless noted.

| Endpoint | Caller | Purpose |
|---|---|---|
| `employee_app.authentication.master_token` | guest | The app's service token |
| `employee_app.authentication.get_employee_login_policy` | service token | Policy for a mobile number |
| `employee_app.authentication.generate_and_send_otp` | service token | Send an OTP by WhatsApp |
| `employee_app.authentication.sign_up_api` | service token | First-time enrollment |
| `employee_app.sign_in.otp_generate_for_sign_in` | guest | Start sign-in: password check or OTP send |
| `employee_app.sign_in.sign_in_api` | service token | Finish sign-in |
| `employee_app.authentication.otp_generate_for_cold_boot` / `cold_boot_api` | service token | High Security re-verification |
| `employee_app.gauth.create_new_password` | service token, **POST only** | OTP-verified password setup |
| `employee_app.authentication.refresh_employee_token` | any token | Refresh |
| `employee_app.gauth.create_refresh_token` | guest | Refresh |

### Matching employees

Mobile numbers are compared exactly, after normalizing to E.164: national format in the site's System Settings country (Saudi Arabia when unset), or international with or without "+".

- Only **Active** employees match.
- A number shared by two Active employees matches neither.

## `get_employee_login_policy`

```json
{
  "status": "success",
  "employee_id": "HR-EMP-00001",
  "authentication": "OTP Authentication",
  "high_security": false,
  "sign_up_policy": {"password_policy": "No", "otp_policy": "Mandatory"},
  "sign_in_policy": {"password_policy": "No", "otp_policy": "Mandatory"},
  "cold_boot_policy": {"password_policy": "No", "otp_policy": "No"},
  "employee_has_existing_password": false,
  "employee_has_signed_up": true,
  "otp_verified_password_setup": false,
  "erp_web_password_setup_allowed": false
}
```

- **Every flag is a JSON boolean.**
- `employee_has_existing_password` is true only for a password the employee chose, never the app's "egf..." placeholder.
- `otp_verified_password_setup` (SDK 0.2.0) is true only when **all** of these hold:
  - the tenant switch `Checkin App Setting.allow_in_app_password_setup` is on (default off);
  - the employee is Active and has signed up;
  - their user is enabled and not an Administrator or System Manager;
  - their sign-in policy uses a password;
  - they are not a Both-mode employee who already has a password;
  - WhatsApp testing mode is off.
- `erp_web_password_setup_allowed` is the same rule for **OTP-only** employees (a password for the ERP website), under its own switch, `allow_erp_password_setup` (default off). Their mobile sign-in stays OTP. The SDK doesn't use it yet; offering it needs a client screen.

## Sign-up, sign-in and cold boot

Success:

```json
{
  "status": "success",
  "data": {
    "token": {"access_token": "…", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "…", "scope": "…"},
    "employee": {"id": "HR-EMP-00001", "employee_name": "…", "phone": "…", "email": null},
    "password_policy": "No",
    "otp_policy": "Mandatory",
    "time": "2026-11-09 12:00:00"
  }
}
```

Sign-up has the same shape without the two policy keys. Errors are flat: `{"status": "error", "message": "…"}`.

| Status | Message |
|---|---|
| 401 | `Invalid or expired OTP` |
| 401 | `Invalid password` |
| 401 | `Invalid credentials or unauthorized`, with `detail` (disabled or missing user) |
| 409 | `Employee has already signed up` (sign-up only) |

- Sign-in **never changes the login password**. The app's placeholder is ignored, and it is never accepted as a password.
- Sign-up saves a password only when the employee chose one. An admin account's current Desk password is checked, never replaced.
- Tokens are issued for the OAuth Client named by `Checkin App Setting.app_key` (the one `master_token` uses), or the site's first client when that isn't set.

## `create_new_password` (POST only)

All replies are nested under `data`; there is no top-level `status`.

```json
{"data": {"status": "success", "message": "Password updated successfully", "employee_id": "HR-EMP-00001"}}
```

| Status | Message |
|---|---|
| 400 | `mobile_no, otp and new_password are required` |
| 400 | `Please choose a different password` (the placeholder, or a password the site's Frappe password policy rejects) |
| 401 | `Invalid or expired OTP` |
| 403 | `Password setup is not available` (neither offer above is true right now) |
| 404 | `No employee user found for the given phone number` |
| 429 | `Too many attempts. Try again later.` |

The order of operations:
1. The employee's row is locked.
2. The offer is checked again.
3. The OTP is spent last, so a refusal leaves it usable.
4. Other sessions end and OAuth tokens are revoked.
5. The new password works on the ERP website login.

## Refresh

| Endpoint | Success | Refused |
|---|---|---|
| `refresh_employee_token` | `{"status": "success", "data": {"token": {…}, "time": "…"}}` | 401 `Invalid or expired refresh token` |
| `create_refresh_token` | `{"data": {…}}` | 401 `{"data": "invalid_grant"}` |

- The refresh token must be a non-empty string.
- Each refresh token works once. One presented again revokes every token of that user, who signs in again, so clients must refresh single-flight.
- Tokens are also revoked when High Security is turned on, when the employee leaves Active, or when their user is disabled.

## Limits and errors

| Limit | Value |
|---|---|
| OTP | 6 digits, valid 5 minutes, single use, 5 wrong codes destroy it |
| Lockout | 10 wrong OTPs or passwords in an hour lock the employee for 15 minutes |
| Sends | 1 per minute and 5 per hour per employee |
| Per IP | 600 per hour per endpoint (`employee_app_ip_limit_per_hour` in site_config) |

- A throttled request gets HTTP 429 `{"status": "error", "message": "Too many attempts. Try again later."}`. `create_new_password` nests it under `data`.
- Unexpected errors return HTTP 500 `{"status": "error", "message": "Something went wrong", "ref": "<id>"}`. The traceback is in the Error Log under that reference, without local variables.

## Site configuration (`site_config.json`)

| Key | Effect |
|---|---|
| `employee_app_service_gate` | `"enforce"` refuses the service token outside the pre-login methods. Unset, those calls are only logged to `logs/employee_app.auth.log` |
| `employee_app_ip_limit_per_hour` | Overrides the per-IP limit |
| `employee_app_test_otp` | A fixed OTP for automated tests, honoured **only** when `developer_mode` is on |
