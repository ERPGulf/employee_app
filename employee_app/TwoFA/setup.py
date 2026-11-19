# Copyright (c) 2026, ERPGulf.com
"""Site setup for two-factor sign-in, run from hooks.py (after_install, after_migrate)."""

from urllib.parse import urlparse

import frappe

DEFAULT_ISSUER = "Frappe Framework"


def site_issuer() -> str:
	"""The site address as an OTP issuer, always with the port: "<host>_<port>".
	From host_name in site_config.json when set, otherwise the site name.
	No port in the address means the default: 443 for https, 80 for http."""
	url = urlparse(frappe.utils.get_url())
	port = url.port or (80 if url.scheme == "http" else 443)
	return f"{url.hostname}_{port}"


def set_otp_issuer():
	"""Set System Settings > OTP Issuer Name to the site address, unless someone already
	chose a name. Safe to run on every migrate."""
	current = frappe.db.get_single_value("System Settings", "otp_issuer_name")
	if current and current != DEFAULT_ISSUER:
		return
	issuer = site_issuer()
	frappe.db.set_single_value("System Settings", "otp_issuer_name", issuer)
	print(f"employee_app: OTP Issuer Name set to {issuer}")