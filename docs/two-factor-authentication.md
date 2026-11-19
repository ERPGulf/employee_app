# Two-factor authentication (2FA) for ERPNext

Part of `employee_app` by ERPGulf.com. This page covers everything: what it does, how to set up a server, how the sign-in flows work for users and admins, Firebase (FCM) for push approval, the mobile app API, and troubleshooting.

**Contents**

1. [What it does](#1-what-it-does)
2. [Code layout](#2-code-layout)
3. [Server setup, step by step](#3-server-setup-step-by-step)
4. [Check a site: `check_setup`](#4-check-a-site-check_setup)
5. [Firebase (FCM) for push approval](#5-firebase-fcm-for-push-approval)
6. [Two-Factor Policy](#6-two-factor-policy)
7. [Administrator account](#7-administrator-account)
8. [Flows](#8-flows)
9. [For users](#9-for-users)
10. [For client admins](#10-for-client-admins)
11. [Mobile app API (push approval)](#11-mobile-app-api-push-approval)
12. [Testing push with curl](#12-testing-push-with-curl)
13. [Troubleshooting](#13-troubleshooting)
14. [Known limits](#14-known-limits)

---

## 1. What it does

Frappe already has two-factor sign-in with an authenticator app (System Settings > Login > "OTP App"). This module builds on it, without editing Frappe core:

| Feature | In short |
|---|---|
| **Locked policy** | Who must use 2FA is set in `site_config.json` by the ERPGulf backend team. Clients cannot weaken it from the screen. Default: every system user. |
| **On-screen QR enrolment** | A new user, or a user whose authenticator was reset, sees the QR code on the sign-in page for 60 minutes, in English and Arabic, with the ERPGulf logo. No email needed. |
| **ERPGulf sign-in screens** | The code screen, errors and expiry messages are bilingual and branded. |
| **Push approval** | Users of the ERPGulf Employee App (Claudion Checkin) can tap **Allow** on their phone instead of typing a code. Typing a code always works too. |
| **Administrator exempt** | Administrator never uses 2FA. It gets a long random password that nobody keeps. |

Supported apps on the phone:

* **Employee App (Claudion Checkin)**: recommended. Shows codes and approves sign-ins with one tap.
* **Google Authenticator** or **Microsoft Authenticator**: codes only. The user types the 6-digit code each time.

---

## 2. Code layout

```
employee_app/
├── TwoFA/
│   ├── __init__.py   overview
│   ├── policy.py     who must use 2FA; Administrator exemption; System Settings guard
│   ├── login.py      web sign-in: QR enrolment window, hooks that apply the policy
│   ├── push.py       push approval logic, check_setup
│   ├── api.py        push approval endpoints (/api/method/employee_app.TwoFA.api.<endpoint>)
│   └── setup.py      after_install / after_migrate: OTP Issuer Name from host_name
├── public/js/2fa/
│   ├── login.js            sign-in screens (QR, code, push status, expiry)
│   └── system_settings.js  "Two-Factor Policy: … Managed by ERPGulf" note
├── public/images/erpgulf-logo-white.png
└── employee_app_for_erpnext/doctype/authenticator_device/   one push phone per user
```

Hooks used (`hooks.py`): `before_login`, `on_login`, `after_install`, `after_migrate`, `doc_events` (User `after_insert`, System Settings `validate`), `override_whitelisted_methods` (Reset OTP Secret), `web_include_js`, `doctype_js`.

Why `TwoFA` and not `2fa`: Python module names cannot start with a digit. The JS folder has no such rule, so it is `2fa`.

How it stays out of Frappe core: the `before_login` hook wraps three functions in `frappe.twofactor` once per worker process (`get_verification_obj`, `two_factor_is_enabled`, `two_factor_is_enabled_for_`). Every case the module does not own is handed back to Frappe's original function, and nothing changes on sites where `employee_app` is not installed.

---

## 3. Server setup, step by step

Run everything from the bench folder, for example `/opt/<bench>/frappe-bench`. Replace `<site>` with the site name.

```mermaid
flowchart TD
    A[Install employee_app] --> B[Set host_name with the real address and port]
    B --> C[bench migrate<br/>sets OTP Issuer Name]
    C --> D[Outgoing email account working]
    D --> E[System Settings: Enable Two Factor Auth, method OTP App]
    E --> F[Administrator: random password]
    F --> G[Optional: whatsapp_saudi + Firebase for push]
    G --> H[check_setup: all PASS]
```

### 3.1 Install the app

```bash
bench get-app https://github.com/ERPGulf/employee_app.git
bench --site <site> install-app employee_app
```

### 3.2 Set `host_name` (important)

`host_name` is the address users actually type, **with the port** if it is not 443.

```bash
bench --site <site> set-config host_name "https://saudi-hrms.erpgulf.com:4030"
```

Why it matters:

* The OTP Issuer Name is built from it (next step). The mobile app uses the issuer to find the server.
* Frappe also uses it for links in emails (password reset, QR link). Without it, links can miss the port and break.

### 3.3 Migrate

```bash
bench --site <site> migrate
bench --site <site> clear-cache
bench restart
```

`migrate` creates the **Authenticator Device** DocType and sets **System Settings > OTP Issuer Name** from `host_name`, for example:

| `host_name` | OTP Issuer Name |
|---|---|
| `https://saudi-hrms.erpgulf.com:4030` | `saudi-hrms.erpgulf.com_4030` |
| `https://erp.racktechlogistics.com` | `erp.racktechlogistics.com_443` |
| `http://x.local` | `x.local_80` |

No port in `host_name` means the default: 443 for https, 80 for http. The `:` becomes `_` because the issuer appears in the QR code's label.

It only replaces the issuer while it is still Frappe's default "Frappe Framework" or empty, so a name someone chose is never overwritten. If `host_name` is not set, it changes nothing and prints a warning. To set it by hand:

```bash
bench --site <site> execute frappe.db.set_single_value --args "['System Settings', 'otp_issuer_name', 'saudi-hrms.erpgulf.com_4030']"
```

Users who scanned a QR before the issuer changed keep the old label in their authenticator app. Their codes still work. Reset them only if you want the new name shown.

### 3.4 Outgoing email

Set up an **Email Account** with **Enable Outgoing** and **Default Outgoing** ticked. Frappe emails the QR setup link to users who never had an on-screen window (see [flows](#8-flows)). For OCI Email Delivery:

| Field | Value |
|---|---|
| SMTP server | `smtp.email.<region>.oci.oraclecloud.com` (no spaces) |
| Port | `587` |
| Use TLS | ticked |
| Use different Email ID | ticked; login = the OCID SMTP username |
| Email address | an OCI **Approved Sender** |

### 3.5 Turn 2FA on

System Settings > Login > Two Factor Authentication:

* Tick **Enable Two Factor Auth**.
* Method: **OTP App**.

The policy (section 6) decides who must use it, so ticking roles is optional under the default policy.

### 3.6 Administrator password

See [section 7](#7-administrator-account):

```bash
bench --site <site> set-admin-password "$(openssl rand -base64 33)"
```

### 3.7 Push approval (optional)

Install `whatsapp_saudi` and configure Firebase as in [section 5](#5-firebase-fcm-for-push-approval). Without it, everything works with typed codes.

### 3.8 Check

```bash
bench --site <site> execute employee_app.TwoFA.push.check_setup
```

---

## 4. Check a site: `check_setup`

```bash
bench --site <site> execute employee_app.TwoFA.push.check_setup
```

Example of a fully set up site:

```
PASS  Two-factor on with method OTP App (now: on, OTP App)
PASS  Who must use it: policy High: all system users; roles with 2FA ticked: All
PASS  OTP Issuer Name 'saudi-hrms.erpgulf.com_4030' matches host_name 'saudi-hrms.erpgulf.com_4030'
PASS  Default outgoing Email Account
PASS  Firebase Notification on in Whatsapp Saudi settings
PASS  Scheduler and background workers active
```

| Line | Meaning | If FAIL |
|---|---|---|
| Two-factor on | System Settings has 2FA enabled with method OTP App | Section 3.5 |
| Who must use it | The policy, and which roles have 2FA ticked | Only fails under Standard with no role ticked |
| OTP Issuer Name | The issuer equals the address built from `host_name` | Set `host_name` (3.2), then migrate or set the issuer by hand (3.3) |
| Default outgoing Email Account | Frappe can send the QR email fallback | Section 3.4 |
| Firebase Notification | `whatsapp_saudi` is installed and Firebase is ticked | Section 5. Push is optional: codes still work |
| Scheduler and workers | Background jobs run (they send the push) | `bench enable-scheduler`, check supervisor |

---

## 5. Firebase (FCM) for push approval

The push ("Login attempt — Log in to … as …") is sent by the `whatsapp_saudi` app, which already contains the Firebase sender. `employee_app` adds no Firebase code.

```mermaid
flowchart LR
    B[Browser sign-in] --> S[employee_app<br/>TwoFA.api.login_start]
    S --> Q[Background job<br/>TwoFA.push._send_push]
    Q --> W[whatsapp_saudi<br/>send_firebase_notification]
    W --> F[(Firebase Cloud Messaging)]
    F --> P[Phone: Employee App]
```

### 5.1 Firebase project

1. Use **the same Firebase project the mobile app is built with**. A token from one project cannot be reached from another.
2. Firebase console > **Project settings** > **Service accounts** > **Generate new private key**. A JSON file downloads. Keep it secret.

### 5.2 Install and configure `whatsapp_saudi`

```bash
bench get-app https://github.com/ERPGulf/whatsapp_saudi.git
bench --site <site> install-app whatsapp_saudi
bench restart
```

In the desk, open **Whatsapp Saudi** (settings):

* Tick **Firebase Notification**.
* Copy each value from the service account JSON into the field of the same name:

| JSON key | Field |
|---|---|
| `type` | Type |
| `project_id` | Project ID |
| `private_key_id` | Private Key ID |
| `private_key` | Private Key (paste as is, including `-----BEGIN PRIVATE KEY-----`) |
| `client_email` | Client Email |
| `client_id` | Client ID |
| `auth_uri` | Auth URI |
| `token_uri` | Token URI |
| `auth_provider_x509_cert_url` | Auth Provider x509 Cert URL |
| `client_x509_cert_url` | Client x509 Cert URL |

Save, then `bench restart` so workers load the new credentials.

### 5.3 Test a push

With a real token from a phone running the app:

```bash
bench --site <site> execute whatsapp_saudi.whatsapp_saudi.doctype.whatsapp_saudi.whatsapp_saudi.test_firebase_push --kwargs "{'client_token': '<token>'}"
```

Then run `check_setup` again: the Firebase line should PASS.

---

## 6. Two-Factor Policy

The policy decides who must use two-factor sign-in. It is **locked**: it lives in `site_config.json`, not in System Settings, so only someone with server access can change it.

| Policy | Who must use 2FA |
|---|---|
| **Maximum: all users** | Every user, system and website. No exceptions (except Administrator, section 7). |
| **High: all system users** *(default)* | Every system (desk) user. Website users only if one of their roles requires it. |
| **Standard: by role** | Only users with a role that has "Two Factor Authentication" ticked. Frappe's own behaviour. |

```bash
# change (backend team only)
bench --site <site> set-config employee_app_twofa_policy "Maximum: all users"
bench --site <site> set-config employee_app_twofa_policy "High: all system users"
bench --site <site> set-config employee_app_twofa_policy "Standard: by role"
```

* No value, or an unknown value, means **High**. A new site is on High without any setup.
* It takes effect at the next sign-in. No restart.
* Under High and Maximum the policy also overrides "Bypass Two Factor Auth for users who login from restricted IP Address", and the **Enable Two Factor Auth** tick: it is greyed out on screen, switched back on if someone saves it off, and ignored for policy users even if changed in the database.
* System Settings > Login shows the current policy: "Two-Factor Policy: High: all system users · Managed by ERPGulf".

```mermaid
flowchart TD
    U[User signs in with password] --> X{Administrator?}
    X -- yes --> N[No 2FA]
    X -- no --> P{Policy}
    P -- Maximum --> Y[2FA required]
    P -- High --> T{System user?}
    T -- yes --> Y
    T -- no --> R
    P -- Standard --> R{A role with 2FA ticked?}
    R -- yes --> Y
    R -- no --> N2[No 2FA]
```

### Emergency: everyone locked out

```bash
bench --site <site> set-config employee_app_twofa_policy "Standard: by role"
bench --site <site> execute frappe.twofactor.disable
```

Sign in, fix the cause, then turn 2FA back on and remove the policy override (`bench --site <site> set-config employee_app_twofa_policy "High: all system users"`).

---

## 7. Administrator account

Administrator **never** uses two-factor sign-in, under every policy. It is the break-glass account, protected differently:

1. Give it a long random password that nobody keeps:

   ```bash
   bench --site <site> set-admin-password "$(openssl rand -base64 33)"
   ```

   * `openssl rand -base64 33` makes 33 random bytes, shown as 44 characters.
   * `$( … )` passes it straight to Frappe. It is not printed, not saved to a file, and your shell history keeps only the command, not the password.
   * After this, nobody knows the password. That is the point.

2. When Administrator is really needed, the backend team sets a known password with the same command (`set-admin-password "<temporary password>"`), uses it, then randomizes it again with the command above.

3. Everyone, including the ERPGulf team, works from their own named user accounts, which do use 2FA.

Also give Administrator a real email (User > Administrator) so Frappe's emails to it have somewhere to go.

Watch for Administrator sign-ins in the **Activity Log**: since it skips 2FA, any use of it should be expected.

---

## 8. Flows

### 8.1 First-time enrolment (on-screen QR)

An admin creates the user, or presses **Reset OTP Secret** on the user. That opens a **60-minute window**. Only admin actions open it: never a user changing their own password, Forgot password, self sign-up, or a user resetting their own secret.

```mermaid
flowchart TD
    A[Admin creates user<br/>or presses Reset OTP Secret] --> W[60-minute window opens]
    W --> S[User signs in with password]
    S --> Q{Window still open?}
    Q -- yes --> QR[Bilingual QR screen<br/>with countdown]
    QR --> SC[User scans with Employee App<br/>or Google / Microsoft Authenticator]
    SC --> C[User types the 6-digit code]
    C --> OK[Signed in. Enrolled.<br/>Window closes]
    Q -- no, expired --> EX[Setup time expired:<br/>contact your administrator]
    EX --> A
```

* The QR is shown only after the password check, and only to users not yet enrolled.
* Frappe's sign-in session lasts 3 minutes. If it times out, the user signs in again: the QR is the same until the window ends.
* After expiry, no QR email is sent. The admin opens a new window with Reset OTP Secret.
* Users who never had a window (for example, un-enrolled before this was installed) keep Frappe's standard behaviour: the QR link is emailed.

### 8.2 Every sign-in after enrolment

```mermaid
flowchart TD
    S[User signs in with password] --> C[Confirm your sign-in screen]
    C --> D{Employee App with push set up?}
    D -- yes --> P[Phone gets 'Login attempt'<br/>User taps Allow]
    P --> OK[Signed in]
    D -- no --> T[User types the 6-digit code<br/>from any authenticator app]
    T --> V{Code correct?}
    V -- yes --> OK
    V -- no --> E[Bilingual error, try again]
    E --> T
```

Typing a code always works, even when push is set up.

### 8.3 Push approval in detail

```mermaid
sequenceDiagram
    participant B as Browser (login.js)
    participant S as ERPNext (TwoFA.api)
    participant F as Firebase
    participant P as Phone (Employee App)

    B->>S: password
    S-->>B: code screen + tmp_id
    B->>S: login_start(tmp_id)
    S->>S: request created, 60 s
    S->>F: push "Login attempt"
    F->>P: notification
    B->>S: login_status (every 2 s)
    S-->>B: pending
    P->>S: pending (signed)
    S-->>P: site, IP, browser, expires_in
    P->>P: unlock with Face ID / PIN, user taps Allow
    P->>S: respond allow (signed)
    S-->>P: approved
    B->>S: login_status
    S-->>B: approved, session cookie
    B->>B: open the desk
```

Rules:

* A request lives **60 seconds**. Then the page offers **Send again**.
* At most **5 pushes per user per 10 minutes**.
* **Deny** also cancels Frappe's sign-in ticket, so a typed code fails for that attempt.
* The phone proves itself with an **Ed25519 signature** on every call; the private key never leaves the phone.

### 8.4 Registering the phone for push

```mermaid
flowchart TD
    S[User signs in on the web<br/>password correct] --> W[30-minute registration window opens]
    W --> A[Employee App scans the QR<br/>or the user adds the account]
    A --> R[App calls register_device<br/>with a current 6-digit code and its public key]
    R --> OK[Phone registered. Push works from the next sign-in]
```

One phone per user. To move to a new phone, the admin presses Reset OTP Secret (section 10).

### 8.5 Lost or new phone

```mermaid
flowchart TD
    L[User lost or changed phone] --> A[User contacts admin]
    A --> R[Admin: User > Password > Reset OTP Secret]
    R --> X[Old authenticator and push phone stop working at once]
    X --> W[60-minute window opens]
    W --> F[Flow 8.1 on the new phone]
```

---

## 9. For users

**First time** (after your admin set up your account):

1. Sign in with your email and password **within 60 minutes**.
2. You see **Set up two-factor sign-in**, in English and Arabic, with a QR code and a countdown.
3. Install **one** app on your phone:
   * **Employee App (Claudion Checkin)**, recommended: you can just tap **Allow** when you sign in.
   * Or **Google Authenticator** / **Microsoft Authenticator**: you type the 6-digit code each time.
4. In the app, tap **+** and scan the QR code.
5. Type the 6-digit code and press **Verify**.

**Every time after:**

* Employee App: tap **Allow** on your phone. Or type the code.
* Google / Microsoft Authenticator: open the app and type the code for this site.

**Good to know:**

* Codes change every 30 seconds. If one fails, wait for the next.
* Your phone's time must be automatic.
* Never share your code or QR code. ERPGulf and your IT team will never ask for it.
* Lost or changed your phone? Contact your administrator.
* Setup page expired? Contact your administrator for a new QR code.

---

## 10. For client admins

| Task | How |
|---|---|
| Add a user | Create the user as usual. Their 60-minute QR window opens automatically. Tell them to sign in within the hour. |
| User missed the 60 minutes | User > Password > **Reset OTP Secret**. A new 60-minute window opens. |
| Lost or new phone | Same: **Reset OTP Secret**. The old authenticator and push phone stop working immediately. |
| See who has a push phone | Search **Authenticator Device**. Delete a record to remove that phone. |
| Change who must use 2FA | Not possible from the screen. Ask ERPGulf support. |
| Turn 2FA off | Not possible from the screen under High or Maximum. Ask ERPGulf support. |

---

## 11. Mobile app API (push approval)

For the mobile team. All endpoints:

```
POST https://<site>/api/method/employee_app.TwoFA.api.<endpoint>
Content-Type: application/json
```

* Plain JSON replies: `{"status": "ok", ...}` or `{"status": "error", "code": "...", "message": "..."}`.
* No bearer token and no cookie on mobile calls. Each call proves itself.
* The site address comes from the QR issuer: `saudi-hrms.erpgulf.com_4030` → `https://saudi-hrms.erpgulf.com:4030`.

### 11.1 Endpoints

| Endpoint | Caller | Proof | Fields after the common ones |
|---|---|---|---|
| `login_start` | sign-in page | Frappe `tmp_id` | `tmp_id`, `resend` |
| `login_status` | sign-in page | Frappe `tmp_id` | `tmp_id` |
| `register_device` | phone | current 6-digit code | `user`, `code`, `device_id`, `public_key`, `push_token`, `platform` (`ios`/`android`), `app_id` |
| `pending` | phone | signature | none |
| `respond` | phone | signature | `request_id`, `action` (`allow`/`deny`) |
| `update_push_token` | phone | signature | `push_token` |
| `unregister` | phone | signature | none |

### 11.2 Signed calls

Every phone call except `register_device` sends `user`, `device_id`, `ts` (phone time, Unix seconds) and `sig`.

`sig` is the base64 Ed25519 signature over these lines joined with `\n`, UTF-8, no trailing newline:

```
<endpoint>
<user>
<device_id>
<ts>
<endpoint's own fields, in the order in the table>
```

Example for `respond`:

```
respond
test02@htsqatar.com
device-abc
1794849185
9f2c...
allow
```

The key pair is made on the phone at registration. The private key stays in the Keychain or Keystore, unlocked by Face ID, fingerprint or PIN. The public key (32 bytes, base64) is sent once in `register_device`.

### 11.3 Replies

`pending`:

```json
{"status": "ok", "request": {"request_id": "9f2c...", "site": "saudi-hrms.erpgulf.com_4030",
 "user": "test02@htsqatar.com", "ip": "37.211.184.179", "browser": "Chrome on macOS",
 "created": "2026-11-19 09:24:06", "expires_in": 42}}
```

`"request": null` means nothing is waiting.

`respond`: `{"status": "ok", "result": "approved" | "denied" | "expired"}`.

### 11.4 Errors

| HTTP | `code` | Meaning | App should |
|---|---|---|---|
| 400 | `bad_request` | Field missing or malformed | Fix the request |
| 401 | `bad_signature` | Signature or device id wrong | Treat as broken enrolment |
| 401 | `clock_skew` | Phone time more than 90 s off; reply has `server_time` | Ask the user to set automatic time |
| 401 | `bad_code` | Wrong code at registration | Let the user retry (5 per hour) |
| 403 | `window_closed` | Registration window not open | "Sign in on the web first, then scan again" |
| 409 | `device_exists` | Another phone is registered | "Ask your admin to reset" |
| 410 | `device_removed` | Admin reset the account | Remove the account, scan the new QR |
| 429 | — | Too many attempts | Wait |
| 500 | — | Server error; reply has a `ref` | Show the ref for support |

---

## 12. Testing push with curl

Use the browser for the sign-in and a shell script as the phone. The script `docs/push2fa_phone.sh` signs requests exactly like the app. Run it on the server (it needs OpenSSL 3; macOS `openssl` cannot make these signatures).

```bash
chmod +x docs/push2fa_phone.sh
SITE=https://saudi-hrms.erpgulf.com:4030 USER_ID=test02@htsqatar.com ./docs/push2fa_phone.sh keys
```

1. **Register:** in the browser, sign in as the user up to the code screen (this opens the 30-minute registration window). Then, with the current code from the user's authenticator app:

   ```bash
   ./docs/push2fa_phone.sh register 482913
   ```

2. **Allow:** sign in again in the browser, then within 60 seconds:

   ```bash
   ./docs/push2fa_phone.sh pending
   ./docs/push2fa_phone.sh respond allow
   ```

   The browser opens the desk within about 2 seconds.

3. **Deny:** sign in again, `pending`, then `respond deny`. The browser shows "denied".

4. **Negative tests:** `neg-badsig` (401 bad_signature), `neg-skew` (401 clock_skew), `neg-replay` (expired).

The script keeps its files in `~/push2fa-test`. `dev.key` can approve sign-ins for that user until you run `./docs/push2fa_phone.sh unregister`, so delete the folder afterwards.

---

## 13. Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| "Something went wrong" at sign-in, 500 in the console | Outgoing email failing while Frappe tries to email the QR | Fix the Email Account (3.4); check `logs/web.error.log` |
| "Verification code email not sent. Please contact Administrator." | User has no on-screen window and email cannot be sent | Admin presses Reset OTP Secret on the user (opens a window); fix email |
| Plain "OTP setup using OTP App was not completed" | `login.js` not loaded | `bench --site <site> clear-cache`, browser hard refresh (Cmd+Shift+R) |
| QR screen shows, code always wrong | Phone time wrong, or wrong account in the app | Automatic time on the phone; check the account name matches the issuer |
| "Setup time expired" | 60-minute window passed | Admin presses Reset OTP Secret |
| check_setup: issuer FAIL | `host_name` missing or issuer still default | Sections 3.2 and 3.3 |
| check_setup: Firebase FAIL | `whatsapp_saudi` not installed or Firebase not ticked | Section 5. Codes still work meanwhile |
| Page says "Open the Employee App to approve, or enter the code" | Push not sent (no Firebase, or no push token) | Section 5; the app should call `update_push_token` |
| `register_device` returns `window_closed` | No correct-password sign-in in the last 30 minutes | Sign in on the web first, then register |
| Everyone locked out | — | Emergency commands in section 6 |
| Administrator asked for a code | Old code without the exemption | Update employee_app; `bench restart` |

Logs: sign-in events go to the `employee_app.auth` log (`logs/employee_app.auth.log`). Codes, secrets, tokens and signatures are never logged.

---

## 14. Known limits

* **API keys and app tokens** do not go through web 2FA. A user with an API key and secret, or a token from the mobile app's own sign-in (`gauth.generate_token_secure`, Employee App OTP sign-in), is not asked for a 2FA code. A separate option to require 2FA for API access is planned. Until then, give API keys only to dedicated integration users.
* **Push needs `whatsapp_saudi`** with Firebase on each site. Without it, users type codes.
* **One push phone per user.**