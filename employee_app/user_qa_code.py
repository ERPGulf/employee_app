import cv2
import frappe
from frappe import _
from frappe.utils.data import add_to_date, get_time, getdate
from erpnext import get_region
from pyqrcode import create as qr_create
from base64 import b64encode
import io
import os
from base64 import b64encode



def create_qr_code(doc, method):
	"""Create QR Code after inserting Sales Inv
	"""
	print("here we are *************")

	data = "youtubel.com"
	urls = qr_create(data)
	urls.png('mypic.png',scale=6)
	img=cv2.imread('mypic.png')
	det = cv2.QRCodeDetector()
	val, pts, st_code = det.detectAndDecode(img)
	print(val)
	# return

	region = "Qatar" # get_region(doc.company)
	
	# if QR Code field not present, do nothing
	if not hasattr(doc, 'qr_code'):
		return

	# # Don't create QR Code if it already exists
	# qr_code = doc.get("qr_code")
	# if qr_code and frappe.db.exists({"doctype": "File", "file_url": qr_code}):
	# 	return
	print("here we are 222 *************")
	fields = frappe.get_meta('User').fields

	for field in fields:
		if field.fieldname == 'qr_code' and field.fieldtype == 'Attach Image':
			# creating qr code for the Sales Invoice
			''' TLV conversion for
			1. Seller's Name
			2. VAT Number
			3. Time Stamp
			4. Invoice Amount
			5. VAT Amount
			'''
			tlv_array = []
			# Sellers Name

			company_name = "Im Seller" # frappe.db.get_value('Company',doc.company,'company_name')
			if not company_name:
				frappe.throw(_('Company name missing for {} in the company document'.format(doc.company)))

			tag = bytes([1]).hex()
			length = bytes([len(company_name.encode('utf-8'))]).hex()
			value = company_name.encode('utf-8').hex()
			tlv_array.append(''.join([tag, length, value]))
			
			user_name = str(doc.username)
			if not user_name:
				frappe.throw(_('User name missing for {} in the  document'))

			tag = bytes([1]).hex()
			length = bytes([len(user_name.encode('utf-8'))]).hex()
			value = user_name.encode('utf-8').hex()
			tlv_array.append(''.join([tag, length, value]))
   
			api_url = "https://dev.erpgulf.com:83343/api/"
			if not api_url:
				frappe.throw(_('API URL is missing for {} in the  document'))

			tag = bytes([1]).hex()
			length = bytes([len(api_url.encode('utf-8'))]).hex()
			value = api_url.encode('utf-8').hex()
			tlv_array.append(''.join([tag, length, value]))

			
			# Joining bytes into one
			tlv_buff = ''.join(tlv_array)

			# base64 conversion for QR Code
			base64_string = b64encode(bytes.fromhex(tlv_buff)).decode()

			qr_image = io.BytesIO()
			url = qr_create(base64_string, error='L')
			url.png(qr_image, scale=2, quiet_zone=1)
			
   			

			# making file
			filename = f"QR-CODE-{doc.name}.png".replace(os.path.sep, "__")
			print(filename)
			_file = frappe.get_doc({
				"doctype": "File",
				"file_name": filename,
				"content": qr_image.getvalue(),
				"is_private": 0
			})

			_file.save()

			# assigning to document
			doc.db_set('qr_code', _file.file_url)
			doc.notify_update()

   
			break


def delete_qr_code_file(doc, method):
	"""Delete QR Code on deleted sales invoice"""

	region = get_region(doc.company)
	if region not in ['Saudi Arabia']:
		return

	if hasattr(doc, 'qr_code'):
		if doc.get('qr_code'):
			file_doc = frappe.get_list('File', {
				'file_url': doc.qr_code,
				'attached_to_doctype': doc.doctype,
				'attached_to_name': doc.name
			})
			if len(file_doc):
				frappe.delete_doc('File', file_doc[0].name)
