# Copyright (c) 2026, ERPGulf.com
"""Two-factor sign-in for ERPNext.

policy.py  who must use 2FA (locked, set in site_config.json)
login.py   web sign-in: on-screen QR enrolment, hooks that apply the policy
push.py    push approval logic ("tap Allow on your phone")
api.py     push approval endpoints: /api/method/employee_app.TwoFA.api.<endpoint>
setup.py   after_install / after_migrate: OTP Issuer Name from the site address

Page scripts: public/js/2fa/login.js, public/js/2fa/system_settings.js
"""
