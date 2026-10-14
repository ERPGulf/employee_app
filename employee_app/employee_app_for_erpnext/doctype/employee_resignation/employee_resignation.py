# Copyright (c) 2026, ERPGulf.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EmployeeResignation(Document):
    pass


@frappe.whitelist()
def create_employee_resignation(resignation_date, reason, employee=None):
    """
    Create an Employee Resignation record in ERPNext
    and upload multiple files using file1, file2, file3, etc.

    The employee is resolved from the authenticated user's Employee record.
    """
    user = frappe.session.user
    employee = frappe.get_value("Employee", {"user_id": user}, "name")
    resignation_doc = frappe.get_doc({
        "doctype": "Employee Resignation",
        "employee": employee,
        "resignation_date": resignation_date,
        "reason": reason,
    })

    resignation_doc.insert()

    file_urls = []
    if frappe.request.files:
        frappe.form_dict.doctype = resignation_doc.doctype
        frappe.form_dict.docname = resignation_doc.name
        frappe.form_dict.fieldname = None
        frappe.form_dict.is_private = 1
        frappe.form_dict.file_url = None
        frappe.form_dict.method = None
        file_urls = frappe.get_attr("employee_app.attendance_api.upload_file")()

    return {
        "name": resignation_doc.name,
        "employee": employee,
        "resignation_date": resignation_date,
        "reason": reason,
        "file_url": file_urls,
    }

