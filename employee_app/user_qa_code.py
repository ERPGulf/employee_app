import cv2
import frappe
from frappe import _
from frappe.utils.data import add_to_date, get_time, getdate
from erpnext import get_region
from pyqrcode import create as qr_create
import base64
from base64 import b64encode
import io
import os







def create_qr_code(doc, method):
	"""Create QR Code after inserting Employee"""
	if not hasattr(doc, 'custom_qr_code'):
		return

	fields = frappe.get_meta('Employee').fields
	auth_client_name = frappe.db.get_value("OAuth Client", {}, "name")
	if auth_client_name:
		auth_client = frappe.get_doc("OAuth Client", auth_client_name)
	else:
		frappe.throw("No OAuth Client found")
	app_name = auth_client.app_name
	if not app_name:
		frappe.throw(_('App name missing in OAuth Client'))

	app_key = base64.b64encode(app_name.encode()).decode("utf-8")

	for field in fields:
		if field.fieldname == 'custom_qr_code' and field.fieldtype == 'Attach Image':

			company_name = frappe.db.get_value('Company', doc.company, 'company_name')
			if not company_name:
				frappe.throw(_('Company name missing for {} in the company document'.format(doc.company)))

			if not doc.name:
				frappe.throw(_('Employee code missing in the document'))

			if not doc.first_name:
				frappe.throw(_('First name missing for {} in the document'.format(doc.name)))

			last_name = doc.last_name if doc.last_name else ""

			# if not doc.custom_photo_:
			# 	frappe.throw(_('Photo missing for {} in the document'.format(doc.name)))

			if not doc.custom_restrict_location and doc.custom_restrict_location != 0:
				frappe.throw(_('Restrict Location missing for {} in the document'.format(doc.name)))

			if not doc.user_id:
				frappe.throw(_('User ID missing for {} in the document'.format(doc.name)))

			if not frappe.local.conf.host_name:
				frappe.throw(_('API URL (host_name) is missing in site config'))

			if not app_key:
				frappe.throw(_('App key could not be generated'))

			cleaned = (
				f"Company: {company_name}"
				f" Employee_Code: {doc.name}"
				f" Full_Name: {doc.first_name}  {last_name}"
				f" Photo: {doc.custom_photo_}"
				f" Restrict Location: {doc.custom_restrict_location}"
				f" User_id: {doc.user_id}"
				f" API: {frappe.local.conf.host_name}"
				f" App_key: {app_key}"
			)

			base64_string = b64encode(cleaned.encode()).decode()

			qr_image = io.BytesIO()
			url = qr_create(base64_string, error='L')
			url.png(qr_image, scale=2, quiet_zone=1)

			filename = f"QR-CODE-{doc.name}.png".replace(os.path.sep, "__")
			_file = frappe.get_doc({
				"doctype": "File",
				"file_name": filename,
				"content": qr_image.getvalue(),
				"is_private": 0
			})

			_file.save()

			doc.db_set('custom_qr_code', _file.file_url)
			doc.notify_update()

			break



def delete_qr_code_file(doc, method):
	"""Delete QR Code on deleted sales invoice"""


	if hasattr(doc, 'custom_qr_code'):
		if doc.get('custom_qr_code'):
			file_doc = frappe.get_list('File', {
				'file_url': doc.custom_qr_code,
				'attached_to_doctype': doc.doctype,
				'attached_to_name': doc.name
			})
			if len(file_doc):
				frappe.delete_doc('File', file_doc[0].name)
