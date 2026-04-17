import frappe
import json
from datetime import date, datetime, timedelta, time
import os
from frappe.utils import cint
from mimetypes import guess_type
from typing import TYPE_CHECKING
from frappe.utils import get_time
from frappe.utils import nowdate
from werkzeug.wrappers import Response
from frappe import _
from hrms.hr.doctype.employee_checkin.employee_checkin import calculate_working_hours
from frappe.utils import get_datetime
from datetime import date
from frappe.utils import getdate, get_datetime
from datetime import timedelta


@frappe.whitelist()
def insert_new_trip(
    employee_id: str,
    trip_start_time: str,
    trip_start_km: str,
    trip_status: str,
    trip_start_location: str = None,
    job_order: str = None,
    trip_type: str = None,
    vehicle_number: str = None,
):
    doc = frappe.get_doc({
        "doctype": "driver trips",
        "employee_id": employee_id,
        "trip_start_time": trip_start_time,
        "trip_starting_km": trip_start_km,
        "trip_start_location": trip_start_location,
        "custom_job_order": job_order,
        "custom_trip_type": trip_type,
        "vehicle_number": vehicle_number,
        "custom_trip_status": trip_status
    })
    doc.insert()
    # frappe.db.commit() removed — Frappe handles transaction commit automatically
    return doc


# api for closing trip and updating the odometer
@frappe.whitelist()
def close_the_trip(
    trip_id: str,
    vehicle_id: str,
    trip_end_km: str = None,
    trip_end_location: str = None,
    trip_status: str = None,
    trip_end_time: str = None,
):
    doc = frappe.get_doc("driver trips", trip_id)
    doc.trip_end_time = trip_end_time
    doc.trip_ending_km = trip_end_km
    doc.trip_end_location = trip_end_location
    doc.custom_trip_status = trip_status
    doc.save()
    frappe.db.set_value("Vehicle", vehicle_id, "last_odometer", trip_end_km)
    return doc


@frappe.whitelist()
def get_latest_open_trip(employee_id: str):
    doc = frappe.get_list(
        "driver trips",
        {"employee_id": employee_id, "custom_trip_status": True},
        [
            "name", "trip_start_time", "custom_starting_km",
            "trip_start_location", "custom_job_order",
            "custom_trip_type", "custom_vehicle_number", "custom_trip_status",
        ],
        order_by="creation desc",
    )
    if doc:
        latest_trip = doc[0]
        trip_details = {
            "trip_no": latest_trip.get("name"),
            "employee": employee_id,
            "start_time": latest_trip.get("trip_start_time"),
            "trip_status": latest_trip.get("custom_trip_status"),
        }
    else:
        trip_details = {"trip_status": 0}
    return trip_details


# API for contract party name.
@frappe.whitelist()
def contract_list(enter_name: str):
    doc = frappe.db.get_list(
        "Contract",
        fields=["party_name"],
        filters={"party_name": ["like", f"{enter_name}%"]},
        as_list=True,
    )
    return doc


@frappe.whitelist()
def vehicle_list(vehicle_no: str, odometer: str, vehicle_model: str):
    doc = frappe.db.get_list(
        "Vehicle",
        fields=["license_plate", "last_odometer", "model"],
        filters={"license_plate": ["like", f"{vehicle_no}%"]},
        as_list=True,
    )
    result = []
    for item in doc:
        vehicle_info = {
            "vehicle_number_plate": item[0],
            "odometer": item[1],
            "vehicle_model": item[2],
        }
        result.append(vehicle_info)
    return result


@frappe.whitelist()
def employee_checkin(employee_code: str, limit_start: int, limit_page_length: int):
    doc = frappe.db.get_list(
        "Employee Checkin",
        fields=["employee_name", "log_type", "time"],
        filters={"employee": ["like", f"{employee_code}"]},
        order_by="time desc",
        limit_start=limit_start,
        limit_page_length=limit_page_length,
    )
    return doc


@frappe.whitelist()
def error_log(limit_start: int, limit_page_length: int):
    doc = frappe.db.get_list(
        "Error Log",
        fields=["method", "error", "name", "seen"],
        order_by="modified desc",
        limit_start=limit_start,
        limit_page_length=limit_page_length,
    )
    return doc


@frappe.whitelist()
def error_log_seen(id: str):
    frappe.db.set_value("Error Log", id, "seen", 1)
    doc = frappe.db.get_list(
        "Error Log",
        fields=["method", "error", "name", "seen"],
        filters={"name": ["like", f"{id}"]},
        order_by="modified desc",
    )
    return doc


@frappe.whitelist()
def list_employee(employee_code: str = None):
    doc = frappe.get_all(
        "Employee",
        fields=["name"],
        filters={"name": employee_code} if employee_code else None,
    )
    return doc


@frappe.whitelist()
def Employee_Checkin(
    employee_checkin: str,
    fieldname: str = None,
    fieldvalue: str = None,
    limit_start: int = 0,
    limit_page_length: int = 10,
):
    if fieldname and fieldvalue is not None:
        frappe.db.set_value("Employee Checkin", employee_checkin, fieldname, fieldvalue)
        # frappe.db.commit() removed — Frappe handles transaction commit automatically
    doc = frappe.db.get_list(
        "Employee Checkin",
        fields=[
            "name", "employee_name", "log_type",
            "time", "device_id", "employee", "skip_auto_attendance",
        ],
        filters={"name": ["like", f"%{employee_checkin}%"]},
        order_by="time desc",
        limit_start=limit_start,
        limit_page_length=limit_page_length,
    )
    return doc


@frappe.whitelist()
def upload_file():
    user = None
    if frappe.session.user == "Guest":
        if frappe.get_system_settings("allow_guests_to_upload_files"):
            ignore_permissions = True
        else:
            raise frappe.PermissionError
    else:
        user: "User" = frappe.get_doc("User", frappe.session.user)
        ignore_permissions = False

    files = frappe.request.files
    file_names = []
    urls = []

    is_private = frappe.form_dict.is_private
    doctype = frappe.form_dict.doctype
    docname = frappe.form_dict.docname
    fieldname = frappe.form_dict.fieldname
    file_url = frappe.form_dict.file_url
    folder = frappe.form_dict.folder or "Home"
    method = frappe.form_dict.method
    filename = frappe.form_dict.file_name
    optimize = frappe.form_dict.optimize
    content = None
    filenumber = 0

    for key, file in files.items():
        filenumber = filenumber + 1
        file_names.append(key)
        file = files[key]
        content = file.stream.read()
        filename = file.filename

        content_type = guess_type(filename)[0]
        if optimize and content_type and content_type.startswith("image/"):
            args = {"content": content, "content_type": content_type}
            if frappe.form_dict.max_width:
                args["max_width"] = int(frappe.form_dict.max_width)
            if frappe.form_dict.max_height:
                args["max_height"] = int(frappe.form_dict.max_height)
            content = optimize_image(**args)

        frappe.local.uploaded_file = content
        frappe.local.uploaded_filename = filename

        if content is not None and (
            frappe.session.user == "Guest" or (user and not user.has_desk_access())
        ):
            filetype = guess_type(filename)[0]

        if method:
            method = frappe.get_attr(method)
            is_whitelisted(method)
            return method()
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "File",
                    "attached_to_doctype": doctype,
                    "attached_to_name": docname,
                    "attached_to_field": fieldname,
                    "folder": folder,
                    "file_name": filename,
                    "file_url": file_url,
                    "is_private": cint(is_private),
                    "content": content,
                }
            ).save(ignore_permissions=ignore_permissions)
            urls.append(doc.file_url)

            if fieldname is not None:
                attach_field = frappe.get_doc(doctype, docname)
                setattr(attach_field, fieldname, doc.file_url)
                attach_field.save(ignore_permissions=True)

    return urls


@frappe.whitelist()
def add_log_based_on_employee_field(
    employee_field_value: str,
    timestamp: str,
    location: str = None,
    device_id: str = None,
    log_type: str = None,
):
    """Add Employee Checkin log entry"""
    try:
        if log_type:
            log_type = get_log_type(employee_field_value, timestamp, log_type)

        doc = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee_field_value,
            "time": timestamp,
            "device_id": device_id,
            "log_type": log_type,
            "custom_employee_chekin_location": location,
        })

        doc.insert(ignore_permissions=True)
        # frappe.db.commit() removed — Frappe handles transaction commit automatically

        return doc

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Add Log Error")
        return {"error": str(e)}


@frappe.whitelist()
def employee(employee_code: str = None, custom_in: str = None):
    if employee_code:
        if frappe.db.exists("Employee", employee_code):
            if custom_in is not None:
                try:
                    checkin_value = int(custom_in)
                    if checkin_value not in [0, 1]:
                        return {"error": "checkin_in must be 0 or 1"}

                    frappe.db.set_value("Employee", employee_code, "custom_in", checkin_value)
                    # frappe.db.commit() removed — Frappe handles transaction commit automatically
                    return {f"Employee {employee_code} custom_in updated to {checkin_value}"}
                except ValueError:
                    return {"error": "checkin_in must be an integer (0 or 1)"}

            return frappe.get_doc("Employee", employee_code)
        else:
            return {"error": f"Employee {employee_code} not found"}
    else:
        return frappe.get_all("Employee", fields=["name"])


@frappe.whitelist()
def get_employee_data(employee_id: str = None):
    try:
        if employee_id:
            data = frappe.db.get_value(
                "Employee",
                employee_id,
                ["name", "employee_name", "custom_in"],
                as_dict=True,
            )

            if not data:
                return Response(
                    json.dumps({"error": "Employee not found"}),
                    status=404,
                    mimetype="application/json",
                )

            child_locations = frappe.get_all(
                "Employee Location Child Table",
                filters={"parent": employee_id, "parenttype": "Employee"},
                fields=["location"],
            )

            location_details = []
            for row in child_locations:
                if not row.location:
                    continue

                loc_data = frappe.db.get_value(
                    "Employee Location",
                    row.location,
                    ["name", "reporting_radius", "reporting_location", "lat", "long"],
                    as_dict=True,
                )

                if loc_data:
                    location_details.append({
                        "location": row.location,
                        "reporting_location": loc_data.get("reporting_location"),
                        "reporting_radius": loc_data.get("reporting_radius"),
                        "latitude": loc_data.get("lat"),
                        "longitude": loc_data.get("long"),
                    })

            result = {
                "name": data.get("name"),
                "first_name": data.get("employee_name"),
                "custom_in": data.get("custom_in"),
                "employee_locations": location_details,
            }
        else:
            result = frappe.get_all("Employee", pluck="name")

        return result

    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="get_employee_data Error")
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist()
def get_attendance_details(employee_id: str = None, limit_start: int = 0, limit_page_length: int = 20):
    try:
        doc = frappe.db.get_list(
            "Employee Checkin",
            fields=[
                "name", "employee_name", "log_type",
                "time", "device_id", "employee", "skip_auto_attendance", "creation",
            ],
            filters={"employee": ["like", f"%{employee_id}%"]},
            order_by="creation desc",
            limit_start=limit_start,
            limit_page_length=limit_page_length,
        )
        return doc

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_attendance_details API Error")
        return {
            "success": False,
            "message": f"An error occurred while fetching attendance: {str(e)}",
            "data": [],
        }


def time_diff_in_minutes(time1, time2):
    """Return absolute difference in minutes between two time/datetime objects"""
    if isinstance(time1, datetime) and isinstance(time2, datetime):
        diff = abs((time1 - time2).total_seconds())

    else:
        dt1 = datetime.combine(datetime.today(), time1)
        dt2 = datetime.combine(datetime.today(), time2)
        diff = abs((dt1 - dt2).total_seconds())


    return diff / 60


def get_shift_info(employee):
    """Return latest shift_type and shift_location for employee"""
    sa = frappe.get_all(
        "Shift Assignment",
        filters=[["employee", "=", employee], ["docstatus", "=", 1]],
        fields=["shift_type", "shift_location"],
        order_by="start_date desc",
        limit=1,
    )
    if sa:
        return sa[0].shift_type, sa[0].shift_location
    return frappe.db.get_value("Employee", employee, "default_shift"), None


@frappe.whitelist()
def is_employee_shift_enabled(employee: str = None):
    """Check if Employee Shift setting is enabled for the given employee"""
    try:
        if not employee:
            return 0
        shift_enabled = frappe.db.get_value("Employee", employee, "custom_employee_shift")
        return shift_enabled or 0
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Employee Shift Setting Fetch Error")
        return 0


from frappe.utils import getdate, flt, now_datetime


@frappe.whitelist()
def get_log_type(employee: str, punch_time: str, log_type: str):
    """Determine log type (IN, OUT, Late Entry, Early Exit) considering shift"""
    try:
        punch_dt = frappe.utils.get_datetime(punch_time)

        if  is_employee_shift_enabled(employee):
            return log_type

        shift_type, shift_location = get_shift_info(employee)
        if not shift_type:
            return log_type or "IN"

        shift_doc = frappe.get_doc("Shift Type", shift_type)

        start_time = get_time(shift_doc.start_time)
        end_time = get_time(shift_doc.end_time)
        late_grace = int(shift_doc.late_entry_grace_period or 0)
        early_grace = int(shift_doc.early_exit_grace_period or 0)

        punch_time_only = get_time(punch_dt)

        if log_type == "IN":
            diff = time_diff_in_minutes(punch_time_only, start_time)
            if punch_time_only > start_time and diff > late_grace:
                return "Late Entry"
            return "IN"

        elif log_type == "OUT":
            diff = time_diff_in_minutes(end_time, punch_time_only)
            if punch_time_only < end_time and diff > early_grace:
                return "Early Exit"
            return "OUT"

        return log_type or "IN"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Log Type Error")
        return log_type or "IN"


def employee_checkin_handler(doc, method):
    """Update Employee custom_in flag based on checkin type"""
    try:
        if doc.log_type in ["OUT", "Early Exit"]:
            frappe.db.set_value("Employee", doc.employee, "custom_in", 0)
        elif doc.log_type in ["IN", "Late Entry"]:
            frappe.db.set_value("Employee", doc.employee, "custom_in", 1)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Employee Checkin Handler Error")


@frappe.whitelist()
def get_expense_claims(employee: str = None, limit: int = 100):
    """API to fetch Expense Claim details"""
    filters = {}
    if employee:
        filters["employee"] = employee

    expense_claims = frappe.get_all(
        "Expense Claim",
        filters=filters,
        fields=["name as id", "employee_name", "approval_status"],
        limit=limit,
        order_by="creation desc",
    )

    result = []
    for claim in expense_claims:
        expenses = frappe.get_all(
            "Expense Claim Detail",
            filters={"parent": claim.id},
            fields=["expense_date", "expense_type", "description", "amount"],
        )
        attachments = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Expense Claim",
                "attached_to_name": claim.id,
            },
            fields=["file_name", "file_url"],
        )
        file_urls = attachments[0].file_url if attachments else None

        for e in expenses:
            result.append({
                "id": claim.id,
                "employee_name": claim.employee_name,
                "expense_date": e.expense_date,
                "expense_type": e.expense_type,
                "description": e.description,
                "amount": e.amount,
                "status": claim.approval_status,
                "file_url": file_urls,
            })

    return result


@frappe.whitelist()
def create_expense_claim(
    employee: str,
    expense_date: str = None,
    amount = None,
    expense_type: str = None,
    description: str = None,
    file_name: str = None,
):

    try:

        if not employee or not amount or not expense_type:
            frappe.throw(_("Employee, Amount, and Expense Type are required"))

        doc = frappe.new_doc("Expense Claim")
        doc.employee = employee
        doc.company = frappe.db.get_default("company")
        doc.currency = frappe.get_cached_value("Company", doc.company, "default_currency")
        doc.exchange_rate = 1

        row = doc.append("expenses", {
            "expense_date": expense_date or nowdate(),
            "expense_type": expense_type,
            "amount": amount,
            "description": description,
            "currency": doc.currency,
        })
        row.exchange_rate = 1
        row.currency = doc.currency

        doc.insert(ignore_permissions=True)
        doc.save()

        file_urls = []
        if frappe.request.files:
            frappe.form_dict.doctype = "Expense Claim"
            frappe.form_dict.docname = doc.name
            frappe.form_dict.is_private = 1

            upload_func = frappe.get_attr("employee_app.attendance_api.upload_file")
            file_urls = upload_func()

        doc.reload()

        data = {
            "id": doc.name,
            "employee": employee,
            "expense_date": expense_date or nowdate(),
            "amount": float(amount),
            "expense_type": expense_type,
            "description": description,
            "status": doc.approval_status,
            "file_url": file_urls,
        }

        return Response(json.dumps(data), status=200, mimetype="application/json")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Expense Claim API Error")
        return Response(
            json.dumps({"error": str(e), "message": "Internal Server Error"}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist()
def create_leave_application(
    employee: str,
    leave_type: str,
    from_date: str,
    to_date: str,
    posting_date: str = None,
    acknowledgement_policy: str = None,
    reason: str = None,
):
    """Create Leave Application from API"""
    try:
        doc = frappe.get_doc({
            "doctype": "Leave Application",
            "employee": employee,
            "leave_type": leave_type,
            "from_date": from_date,
            "to_date": to_date,
            "posting_date": posting_date or frappe.utils.nowdate(),
            "description": reason or "",
            "company": frappe.defaults.get_user_default("Company"),
            "custom_acknowledgement_policy1": acknowledgement_policy if acknowledgement_policy else None,
        })
        doc.insert(ignore_permissions=True)
        # frappe.db.commit() removed — Frappe handles transaction commit automatically

        data = {
            "id": doc.name,
            "employee": doc.employee,
            "leave_type": doc.leave_type,
            "from_date": str(doc.from_date),
            "to_date": str(doc.to_date),
            "posting_date": str(doc.posting_date),
            "status": doc.status,
            "agreement": doc.custom_agreement,
        }

        return Response(json.dumps(data), status=200, mimetype="application/json")

    except Exception as e:
        frappe.log_error(message=str(e), title="Leave API Error")
        return Response(
            json.dumps({"error": str(e), "message": "Internal Server Error"}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist()
def get_total_hours(employee: str, date: str):


    try:
        date_obj = getdate(date)
    except Exception:
        date_obj = getdate(date)


    start_datetime = get_datetime(date_obj)
    end_datetime = start_datetime + timedelta(days=1)

    checkins = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start_datetime, end_datetime]],
        },
        fields=["time", "log_type"],
        order_by="time asc",
    )

    total_work_seconds = 0
    last_in_time = None

    for c in checkins:
        if c.log_type == "IN":
            last_in_time = c.time
        elif c.log_type == "OUT" and last_in_time:
            total_work_seconds += (c.time - last_in_time).total_seconds()
            last_in_time = None

    breaks = frappe.get_all(
        "Employee Break",
        filters={
            "employee": employee,
            "time": ["between", [start_datetime, end_datetime]],
        },
        fields=["time", "log_type"],
        order_by="time asc",
    )

    total_break_seconds = 0
    last_break_start = None

    for b in breaks:
        if b.log_type == "IN":
            if not last_break_start:
                last_break_start = b.time
        elif b.log_type == "OUT" and last_break_start:
            total_break_seconds += (b.time - last_break_start).total_seconds()
            last_break_start = None

    net_seconds = max(total_work_seconds - total_break_seconds, 0)

    hours = int(net_seconds // 3600)
    minutes = int((net_seconds % 3600) // 60)

    return f"{hours:02d}:{minutes:02d}"

@frappe.whitelist()
def get_monthly_hours(employee: str, month: str, year: str):
    import calendar

    month_int = int(month)
    year_int = int(year)

    total_minutes = 0
    days = calendar.monthrange(year_int, month_int)[1]

    for day in range(1, days + 1):
        date_str = f"{year_int}-{month_int:02d}-{day:02d}"
        daily_hours = get_total_hours(employee, date_str)  # returns "HH:MM"

        # Replaced map() with direct split + int conversion (fixes frappe-no-functional-code)
        parts = daily_hours.split(":")
        h = int(parts[0])
        m = int(parts[1])
        total_minutes += h * 60 + m

    final_hours = total_minutes // 60
    final_minutes = total_minutes % 60

    return f"{final_hours:02d}:{final_minutes:02d}"


# Security note: get_server_time is intentionally public (no sensitive data exposed)
@frappe.whitelist(allow_guest=True)
def get_server_time():
    return {
        "server_time": frappe.utils.now()
    }


ISSUE_DATE = "2024-01-01"
EXPIRY_DATE = "2026-01-01"
DAYS_REMAINING = 400


@frappe.whitelist(allow_guest=False)
def get_shortcut_2(employee: str):
    settings = frappe.get_single("Checkin App Setting")
    employee_meta = frappe.get_meta("Employee")

    employee_fields = {df.fieldname for df in employee_meta.fields}

    valid_fields = []
    missing_fields = []

    related_fields = [
        settings.field21,
        settings.field22,
        settings.field32,
        settings.field42,
        settings.field52,
    ]

    for field_label in related_fields:
        if not field_label:
            continue
        fieldname = frappe.scrub(field_label)
        if fieldname in employee_fields:
            valid_fields.append(fieldname)
        else:
            missing_fields.append(fieldname)

    if missing_fields:
        return {
            "status": "error",
            "message": "Some fields are missing in Employee DocType",
            "missing_fields": missing_fields,
        }

    emp_doc = frappe.get_doc("Employee", employee)
    field_values = {}
    for field in valid_fields:
        clean_name = field.replace("custom_", "", 1) if field.startswith("custom_") else field
        field_values[clean_name] = emp_doc.get(field)

    return {
        "status": "success",
        "shortcut": settings.shortcut_2,
        "fields": field_values,
    }


@frappe.whitelist(allow_guest=False)
def get_shortcut_1(employee: str):
    settings = frappe.get_single("Checkin App Setting")
    employee_meta = frappe.get_meta("Employee")

    employee_fields = {df.fieldname for df in employee_meta.fields}

    valid_fields = []
    missing_fields = []

    related_fields = [
        settings.field1,
        settings.field2,
        settings.field3,
        settings.field4,
        settings.field5,
    ]

    for field_label in related_fields:
        if not field_label:
            continue
        fieldname = frappe.scrub(field_label)
        if fieldname in employee_fields:
            valid_fields.append(fieldname)
        else:
            missing_fields.append(fieldname)

    if missing_fields:
        return {
            "status": "error",
            "message": "Some fields are missing in Employee DocType",
            "missing_fields": missing_fields,
        }

    emp_doc = frappe.get_doc("Employee", employee)
    field_values = {}
    for field in valid_fields:
        clean_name = field.replace("custom_", "", 1) if field.startswith("custom_") else field
        field_values[clean_name] = emp_doc.get(field)

    return {
        "status": "success",
        "shortcut": settings.shortcut_1,
        "data": field_values,
    }


@frappe.whitelist(allow_guest=False)
def get_shortcut_3(employee: str):
    settings = frappe.get_single("Checkin App Setting")
    employee_meta = frappe.get_meta("Employee")

    employee_fields = {df.fieldname for df in employee_meta.fields}

    valid_fields = []
    missing_fields = []

    related_fields = [
        settings.field13,
        settings.field23,
        settings.field33,
        settings.field34,
        settings.field35,
    ]

    for field_label in related_fields:
        if not field_label:
            continue
        fieldname = frappe.scrub(field_label)
        if fieldname in employee_fields:
            valid_fields.append(fieldname)
        else:
            missing_fields.append(fieldname)

    if missing_fields:
        return {
            "status": "error",
            "message": "Some fields are missing in Employee DocType",
            "missing_fields": missing_fields,
        }

    emp_doc = frappe.get_doc("Employee", employee)
    field_values = {}
    for field in valid_fields:
        clean_name = field.replace("custom_", "", 1) if field.startswith("custom_") else field
        field_values[clean_name] = emp_doc.get(field)

    return {
        "status": "success",
        "shortcut": settings.shortcut_3,
        "data": field_values,
    }


@frappe.whitelist(allow_guest=False)
def qr_code(employee: str):
    emp = frappe.get_doc("Employee", employee)

    if not emp.custom_qr_code:
        return {
            "status": "error",
            "message": "No image found for this employee",
        }

    return {
        "status": "success",
        "employee": employee,
        "image_url": frappe.local.conf.host_name + emp.custom_qr_code,
    }


@frappe.whitelist(allow_guest=False)
def get_leave_type(employee: str):
    allocated_leave_types = frappe.get_list(
        "Leave Allocation",
        fields=["leave_type"],
        filters={"employee": employee},
        pluck="leave_type",
    )
    lwp_leave_types = frappe.get_list(
        "Leave Type",
        fields=["name"],
        filters={"is_lwp": 1},
        pluck="name",
    )
    all_leave_types = list(set(allocated_leave_types + lwp_leave_types))
    return all_leave_types


@frappe.whitelist()
def get_notification(employee: str):
    notifications = frappe.db.get_all(
        "Employee Notification",
        fields=["name", "tittle as title", "notification", "read", "date", "employee", "type"],
        filters={"employee": employee},
    )
    return notifications


@frappe.whitelist()
def mark_notification_as_read(id: str):
    frappe.db.set_value("Employee Notification", id, "read", 1)
    # Manual commit intentionally kept here to immediately persist notification
    # read-state which is a UI-driven non-transactional update. # nosemgrep
    frappe.db.commit()  # nosemgrep

    return {
        "status": "success",
        "message": "Notification marked as read",
    }


@frappe.whitelist()
def get_expense_claim_type():
    doc = frappe.get_list("Expense Claim Type", fields=["name"])
    expense_types = [d["name"] for d in doc]
    return expense_types



@frappe.whitelist(allow_guest=True)
def create_complaint(employee: str, date: str, message: str):
    try:
        doc = frappe.get_doc({
            "doctype": "Employee Complaint",
            "date": date,
            "employee": employee,
            "message": message,
        })
        doc.insert(ignore_permissions=True)

        return {
            "name": doc.name,
            "employee": doc.employee,
            "date": doc.date,
            "message": doc.message,
        }

    except Exception as e:
        frappe.log_error(
            title="Create Employee Complaint Failed",
            message=frappe.get_traceback(),
        )
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def Employee_break(
    employee_field_value: str,
    timestamp: str,
    location: str = None,
    device_id: str = None,
    log_type: str = None,
):
    """Add Employee Break log entry"""
    try:
        last_log = get_last_log(employee_field_value)
        checkin_id = None

        if last_log and last_log.log_type == "IN":
            checkin_id = last_log.name

        if log_type:
            log_type = get_log_type(employee_field_value, timestamp, log_type)

        doc = frappe.get_doc({
            "doctype": "Employee Break",
            "employee": employee_field_value,
            "time": timestamp,
            "device_id": device_id,
            "log_type": log_type,
            "custom_employee_chekin_location": location,
            "employee_checkin": checkin_id,
        })

        doc.insert(ignore_permissions=True)


        return doc

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Add Log Error")
        return {"error": str(e)}


@frappe.whitelist()
def get_last_log(employee: str):
    return frappe.db.get_value(
        "Employee Checkin",
        {"employee": employee},
        ["name", "log_type", "time"],
        order_by="time desc",
        as_dict=True,
    )




@frappe.whitelist()
def get_employee_working_hours(employee, date):

    logs = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]]
        },
        fields=["time", "log_type"],
        order_by="time asc"
    )

    if not logs:
        return 0

    logs = [frappe._dict(log) for log in logs]

    shift = frappe.db.get_value("Shift Assignment", {
        "employee": employee,
        "start_date": ["<=", date],
        "end_date": [">=", date]
    }, "shift_type")

    if not shift:
        return 0

    shift_doc = frappe.get_doc("Shift Type", shift)



    shift_start = get_datetime(date) + shift_doc.start_time
    shift_end = get_datetime(date) + shift_doc.end_time


    if shift_doc.end_time < shift_doc.start_time:
        shift_end += timedelta(days=1)


    filtered_logs = [
        log for log in logs
        if shift_start <= log.time <= shift_end
    ]

    if not filtered_logs:
        return 0

    working_hours = calculate_working_hours(
        filtered_logs,
        shift_doc.determine_check_in_and_check_out,
        shift_doc.working_hours_calculation_based_on
    )

    total_hours = working_hours[0] if working_hours else 0
    return total_hours

@frappe.whitelist()
def get_break_hours(employee, date):

    if isinstance(date, str):
        date = datetime.strptime(date, "%Y-%m-%d").date()

    shift_assignment = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "start_date": ["<=", date],
            "end_date": [">=", date],
        },
        fields=["shift_type"],
        limit=1
    )

    if not shift_assignment:
        return 0

    shift_type = shift_assignment[0].shift_type
    shift = frappe.get_doc("Shift Type", shift_type)


    base_datetime = datetime(date.year, date.month, date.day)

    start_datetime = base_datetime + shift.start_time
    end_datetime = base_datetime + shift.end_time

    # Handle night shift
    if shift.end_time < shift.start_time:
        end_datetime += timedelta(days=1)

    breaks = frappe.get_all(
        "Employee Break",
        filters={
            "employee": employee,
            "time": ["between", [start_datetime, end_datetime]],
        },
        fields=["time", "log_type"],
        order_by="time asc",
    )

    total_break_seconds = 0
    last_break_start = None

    for b in breaks:
        if b.log_type == "IN":
            if not last_break_start:
                last_break_start = b.time

        elif b.log_type == "OUT" and last_break_start:
            total_break_seconds += (b.time - last_break_start).total_seconds()
            last_break_start = None

    return total_break_seconds / 3600

@frappe.whitelist()
def get_today_breaks(employee):


    today = date.today()
    start_datetime = get_datetime(today)
    end_datetime = start_datetime + timedelta(days=1) - timedelta(seconds=1)

    logs = frappe.get_all(
        "Employee Break",
        filters={
            "employee": employee,
            "time": ["between", [start_datetime, end_datetime]],
        },
        fields=["time", "log_type"],
        order_by="time asc",
    )

    breaks = []
    total_seconds = 0
    current_break = None

    for log in logs:

        if log.log_type == "IN":
            if not current_break:
                current_break = {"start": log.time}

        elif log.log_type == "OUT":
            if current_break:
                current_break["end"] = log.time

                duration = (log.time - current_break["start"]).total_seconds()
                current_break["duration_minutes"] = round(duration / 60, 2)

                total_seconds += duration
                breaks.append(current_break)

                current_break = None


    if current_break:
        current_break["end"] = None
        current_break["status"] = "ongoing"
        breaks.append(current_break)

    return {
        "employee": employee,
        "date": str(today),
        "total_break_minutes": round(total_seconds / 60, 2),
        "breaks": breaks
    }




@frappe.whitelist()
def override_working_hours(doc, method):
    if not doc.employee or not doc.attendance_date:
        return


    has_break = frappe.db.exists(
        "Employee Break",
        {
            "employee": doc.employee,
            "time": ["between", [f"{doc.attendance_date} 00:00:00", f"{doc.attendance_date} 23:59:59"]]
        }
    )


    if not has_break:
        return


    approved_break = frappe.db.exists(
        "Break Application",
        {
            "employee": doc.employee,
            "date": doc.attendance_date,
            "status": "Approved"
        }
    )
    frappe.log_error("Approved Break",approved_break)

    if approved_break:
        doc.custom_break_application_approved = 1
    else:
        doc.custom_break_application_approved = 0

    working_hours = get_employee_working_hours(doc.employee, doc.attendance_date)
    break_hours = get_break_hours(doc.employee, doc.attendance_date)

    net_hours = max(working_hours - break_hours, 0)
    doc.custom_break_hours = break_hours
    doc.working_hours = round(net_hours, 2)

