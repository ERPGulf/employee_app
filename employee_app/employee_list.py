import json

import frappe
from werkzeug.wrappers import Response

STATUS_MAP = {0: "Open", 1: "Approved", 2: "Cancelled"}


@frappe.whitelist()
def list_attendance_request(limit_start: int = 0, limit_page_length: int = 20):
    """List Attendance Request records for the logged-in employee"""
    try:
        user = frappe.session.user
        employee = frappe.get_doc("Employee", {"user_id": user})

        if not employee:
            return Response(
                json.dumps({"error": "Employee not found"}),
                status=404,
                mimetype="application/json",
            )

        requests = frappe.get_all(
            "Attendance Request",
            filters={"employee": employee.name},
            fields=[
                "name", "employee", "employee_name", "from_date", "to_date",
                "custom_from_time", "custom_to_time", "reason", "explanation",
                "half_day", "docstatus",
            ],
            order_by="creation desc",
            limit_start=limit_start,
            limit_page_length=limit_page_length,
        )

        result = []
        for r in requests:
            attachments = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Attendance Request",
                    "attached_to_name": r.name,
                },
                fields=["file_name", "file_url"],
            )
            file_urls = attachments[0].file_url if attachments else None

            result.append({
                "name": r.name,
                "employee": r.employee,
                "employee_name": r.employee_name,
                "from_date": str(r.from_date),
                "to_date": str(r.to_date),
                "from_time": r.custom_from_time,
                "to_time": r.custom_to_time,
                "reason": r.reason,
                "explanation": r.explanation,
                "half_day": r.half_day,
                "status": STATUS_MAP.get(r.docstatus, "Unknown"),
                "file_url": file_urls,
            })

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "list_attendance_request API Error")
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist()
def list_loan_application(limit_start: int = 0, limit_page_length: int = 20):
    """List Loan Application records for the logged-in employee"""
    try:
        user = frappe.session.user
        employee = frappe.get_doc("Employee", {"user_id": user})

        if not employee:
            return Response(
                json.dumps({"error": "Employee not found"}),
                status=404,
                mimetype="application/json",
            )

        applications = frappe.get_all(
            "Loan Application",
            filters={"applicant_type": "Employee", "applicant": employee.name},
            fields=[
                "name", "applicant", "applicant_email_address", "loan_product",
                "loan_amount", "company", "posting_date", "status",
                "custom_reason", "repayment_method", "repayment_amount",
            ],
            order_by="creation desc",
            limit_start=limit_start,
            limit_page_length=limit_page_length,
        )

        result = []
        for a in applications:
            attachments = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Loan Application",
                    "attached_to_name": a.name,
                },
                fields=["file_name", "file_url"],
            )
            file_urls = attachments[0].file_url if attachments else None

            result.append({
                "name": a.name,
                "applicant": a.applicant,
                "applicant_email_address": a.applicant_email_address,
                "loan_product": a.loan_product,
                "loan_amount": a.loan_amount,
                "company": a.company,
                "posting_date": str(a.posting_date),
                "status": a.status,
                "reason": a.custom_reason,
                "repayment_method": a.repayment_method,
                "repayment_amount": a.repayment_amount,
                "file_url": file_urls,
            })

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "list_loan_application API Error")
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist()
def list_leave_application(limit_start: int = 0, limit_page_length: int = 20):
    """List Leave Application records for the logged-in employee"""
    try:
        user = frappe.session.user
        employee = frappe.get_doc("Employee", {"user_id": user})

        if not employee:
            return Response(
                json.dumps({"error": "Employee not found"}),
                status=404,
                mimetype="application/json",
            )

        applications = frappe.get_all(
            "Leave Application",
            filters={"employee": employee.name},
            fields=[
                "name", "employee", "employee_name", "leave_type",
                "from_date", "to_date", "half_day", "total_leave_days",
                "description", "posting_date", "status",
            ],
            order_by="creation desc",
            limit_start=limit_start,
            limit_page_length=limit_page_length,
        )

        result = []
        for a in applications:
            attachments = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Leave Application",
                    "attached_to_name": a.name,
                },
                fields=["file_name", "file_url"],
            )
            file_urls = attachments[0].file_url if attachments else None

            result.append({
                "name": a.name,
                "employee": a.employee,
                "employee_name": a.employee_name,
                "leave_type": a.leave_type,
                "from_date": str(a.from_date),
                "to_date": str(a.to_date),
                "half_day": a.half_day,
                "total_leave_days": a.total_leave_days,
                "reason": a.description,
                "posting_date": str(a.posting_date),
                "status": a.status,
                "file_url": file_urls,
            })

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "list_leave_application API Error")
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json",
        )
