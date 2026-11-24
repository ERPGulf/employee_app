# Authentication changes, 24 Nov 2026

Branch: `fix/auth-updates` (not yet committed)

## Summary

- **Admin accounts:** System Manager and Administrator employees now sign up and set passwords the same way as other employees.
- **Password policy "No" (OTP Authentication):** sign-up and sign-in no longer require a password. The OTP is still required.
- **Password policy "Optional":** sign-up and sign-in accept a request with no password. Sign-in still needs either an OTP or a password.

**Action for the mobile app team:** one error message from `sign_in_api` changed and two are new. See [Reply changes](#reply-changes-for-api-clients).

## 1. Admin and System Manager restrictions removed

| Before | Now |
|---|---|
| At sign-up, an admin had to enter their existing ERP password and got a 401 if they chose a new one: "This account has System Manager / Administrator access…" | An admin's chosen password is saved, like any employee's. |
| `otp_verified_password_setup` and `erp_web_password_setup_allowed` were always `false` for admins, so `create_new_password` refused them with 403. | Admins get these offers under the same rules as other employees. |

Code: the check in `sign_up_api` was removed. `is_privileged()` and `PRIVILEGED_ROLES` were deleted from `auth_core.py` because nothing else used them.

> **Security note:** An admin account's password can now be set with an OTP alone, through sign-up or `create_new_password`. Anyone who has an admin's phone, and can read the WhatsApp OTP on it, can set a new password for that System Manager account, which also works on the ERP website. Both password-setup offers are still off by default (`allow_in_app_password_setup` and `allow_erp_password_setup` in Checkin App Setting).

## 2. Sign-up (`sign_up_api`)

| Sign-up password policy | Before | Now |
|---|---|---|
| **No** (OTP Authentication) | A password was required; the app sent its "egf…" placeholder. | No password needed. Any password sent is ignored and never saved. |
| **Optional** (Optional authentication) | A password or the placeholder was required. | The password can be left out. If one is sent, it is checked and saved as before. |
| **Mandatory** (Password Authentication, Both) | A real password was required. | No change. |

The OTP is still required for every sign-up.

## 3. Sign-in (`sign_in_api`)

| Sign-in password policy | Before | Now |
|---|---|---|
| **No** (OTP Authentication) | A password was required (the placeholder). | No password needed; the OTP is required. |
| **Optional** (Optional authentication) | A password was required, even when an OTP was sent. | Send either an OTP or a matching password. If neither is sent, the request is refused with 400. |
| **Mandatory** (Password Authentication, Both) | A password was required. | No change. |

`otp_generate_for_sign_in` and the cold boot flow did not change.

A request with only a mobile number never gets a token: every policy still needs an OTP, a password, or both.

## Reply changes for API clients

`sign_in_api`:

| Status | Before | Now |
|---|---|---|
| 400 | `mobile_no and password are required` | `mobile_no is required` (sent only when `mobile_no` is missing) |
| 400 | — | `Password is required` (Mandatory policy, no password) |
| 400 | — | `OTP or password is required` (Optional policy, neither sent) |

`sign_up_api`: replies did not change. `password is required` is now sent only for the Mandatory policy.

The app can keep sending the "egf…" placeholder; it is still ignored. For OTP-only and Optional employees, the app can now leave `password` out instead.

## Files changed

| File | Change |
|---|---|
| `employee_app/authentication.py` | Admin check removed from `sign_up_api`; password is optional for "No" and "Optional" sign-up policies |
| `employee_app/sign_in.py` | `sign_in_api` checks the password according to the policy |
| `employee_app/auth_core.py` | `is_privileged` and `PRIVILEGED_ROLES` removed |
| `employee_app/tests/test_auth_remediation.py` | Admin tests updated; 8 tests added |
| `docs/auth-api-contract.md` | Updated to match |

## Tests

Tests added:

- `test_otp_only_sign_up_needs_no_password`
- `test_otp_only_sign_up_ignores_a_sent_password`
- `test_optional_sign_up_needs_no_password`
- `test_otp_only_sign_in_needs_no_password`
- `test_otp_only_sign_in_still_needs_the_otp`
- `test_optional_sign_in_with_otp_needs_no_password`
- `test_optional_sign_in_needs_otp_or_password`
- `test_password_sign_in_still_needs_a_password`

Tests changed to expect the new admin behaviour:

- `test_admin_signs_up_like_any_employee` (previously `test_sign_up_never_sets_an_admin_password`)
- `test_promise_by_employee_state`
- `test_erp_offer_is_separate_and_off_by_default`
- `test_endpoint_refuses_whenever_the_promise_is_false`

The tests have not been run yet. Tests are turned off on the development site. To run them:

```bash
bench --site malavika16.erpgulf.com set-config allow_tests true
bench --site malavika16.erpgulf.com run-tests --module employee_app.tests.test_auth_remediation
```
