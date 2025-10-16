import frappe
import json
from datetime import datetime, timedelta,time
import os
from frappe.utils import cint
from mimetypes import guess_type
from typing import TYPE_CHECKING
from frappe.utils import get_time

@frappe.whitelist()
def insert_new_trip(employee_id, trip_start_time, trip_start_km,trip_status,trip_start_location = None,job_order=None, trip_type=None, vehicle_number=None):
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
        frappe.db.commit()
        return doc

#api for  closing trip and updatating the odo-meter
@frappe.whitelist()
def close_the_trip(trip_id,vehicle_id, trip_end_km=None, trip_end_location=None, trip_status=None, trip_end_time=None):
        doc = frappe.get_doc("driver trips", trip_id)
        doc.trip_end_time = trip_end_time
        doc.trip_ending_km = trip_end_km
        doc.trip_end_location = trip_end_location
        doc.custom_trip_status = trip_status
        doc.save()
        frappe.db.set_value("Vehicle",vehicle_id, "last_odometer", trip_end_km)
        return doc

@frappe.whitelist()
def get_latest_open_trip(employee_id):
        doc = frappe.get_list("driver trips", {"employee_id": employee_id, "custom_trip_status": True}, ["name", "trip_start_time", "custom_starting_km", "trip_start_location", "custom_job_order", "custom_trip_type", "custom_vehicle_number", "custom_trip_status"], order_by="creation desc")
        if doc:
            latest_trip = doc[0]
            trip_details = {
                "trip_no": latest_trip.get("name"),
                "employee": employee_id,
                "start_time": latest_trip.get("trip_start_time"),
                "trip_status":latest_trip.get("custom_trip_status")
            }
        else:
            trip_details =  {"trip_status": 0}
        return trip_details

#API for contract  party name.
@frappe.whitelist()
def contract_list(enter_name):
     doc = frappe.db.get_list('Contract',fields=['party_name',],filters={'party_name': ['like', f'{enter_name}%']},as_list=True,)
     return doc



@frappe.whitelist()
def vehicle_list(vehicle_no,odometer,vehicle_model):
     doc = frappe.db.get_list('Vehicle',fields=['license_plate','last_odometer','model'],filters={'license_plate': ['like', f'{vehicle_no}%']},as_list=True,)
     result=[]
     for item in doc:
            vehicle_info = {
                'vehicle_number_plate': item[0],
                'odometer': item[1],
                'vehicle_model': item[2]
            }
            result.append(vehicle_info)

     return result


@frappe.whitelist()
def employee_checkin(employee_code,limit_start,limit_page_length):
    doc = frappe.db.get_list(
        'Employee Checkin',
        fields=['employee_name', 'log_type', 'time'],
        filters={'employee': ['like', f'{employee_code}']},
        order_by='time desc',
        limit_start=limit_start,
        limit_page_length=limit_page_length
    )
    return doc

@frappe.whitelist()
def error_log(limit_start,limit_page_length):
    doc = frappe.db.get_list(
        'Error Log',
        fields=['method', 'error', 'name','seen'],
        order_by='modified desc',
        limit_start=limit_start,
        limit_page_length=limit_page_length
    )
    return doc

@frappe.whitelist()
def error_log_seen(id):
    frappe.db.set_value('Error Log',id, 'seen', 1)
    doc = frappe.db.get_list(
        'Error Log',
        fields=['method', 'error', 'name', 'seen'],
        filters={'name': ['like', f'{id}']},
        order_by='modified desc',
    )
    return doc




@frappe.whitelist(allow_guest=True)
def list_employee(employee_code=None):
    doc=frappe.get_all("Employee",fields=["name"],filters={"name":employee_code} if employee_code else None)
    return doc



@frappe.whitelist(allow_guest=True)


def Employee_Checkin(employee_checkin, fieldname=None, fieldvalue=None, limit_start=0, limit_page_length=10):
    if fieldname and fieldvalue is not None:
        frappe.db.set_value("Employee Checkin", employee_checkin, fieldname, fieldvalue)
        frappe.db.commit()
    doc = frappe.db.get_list(
        'Employee Checkin',
        fields=['name', 'employee_name', 'log_type', 'time','device_id','employee','skip_auto_attendance'],
        filters={'name': ['like', f'%{employee_checkin}%']},
        order_by='time desc',
        limit_start=limit_start,
        limit_page_length=limit_page_length
    )
    return doc



@frappe.whitelist(allow_guest=True)
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
    for key,file in files.items():
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
                            # if filetype not in ALLOWED_MIMETYPES:
                            #     frappe.throw(_("You can only upload JPG, PNG, PDF, TXT or Microsoft documents."))

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
                                attach_field = frappe.get_doc(doctype, docname) #.save(ignore_permissions = True)
                                setattr(attach_field, fieldname, doc.file_url)
                                attach_field.save(ignore_permissions = True)


    return urls




@frappe.whitelist()
def add_log_based_on_employee_field(employee_field_value, timestamp, device_id=None, log_type=None):
    try:


        if log_type:
            log_type = get_log_type(employee_field_value, timestamp,log_type)

        doc = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee_field_value,
            "time": timestamp,
            "device_id": device_id,
            "log_type": log_type
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return doc

    except Exception as e:
        frappe.log_error(message=str(e), title="Add Log Error")
        return {"error": str(e)}





@frappe.whitelist()
def employee(employee_code=None, custom_in=None):
    if employee_code:
        if frappe.db.exists("Employee", employee_code):


            if custom_in is not None:
                try:
                    checkin_value = int(custom_in)
                    if checkin_value not in [0, 1]:
                        return {"error": "checkin_in must be 0 or 1"}

                    frappe.db.set_value("Employee", employee_code, "custom_in", checkin_value)
                    frappe.db.commit()
                    return { f"Employee {employee_code} custom_in updated to {checkin_value}"}
                except ValueError:
                    return {"error": "checkin_in must be an integer (0 or 1)"}


            return frappe.get_doc("Employee", employee_code)

        else:
            return {"error": f"Employee {employee_code} not found"}
    else:

        return frappe.get_all("Employee", fields=["name"])



@frappe.whitelist()
def get_employee_data(employee_id=None):
    if employee_id:
        data = frappe.db.get_value(
            "Employee",
            employee_id,
            ["name", "first_name", "custom_reporting_location", "custom_reporting_radius", "custom_in"],
            as_dict=True
        )

        return data or {}

    else:
        employees = frappe.get_all("Employee", pluck="name")
        return employees



@frappe.whitelist()
def get_attendance_details(employee_id=None, limit_start=0, limit_page_length=20):


    try:
        doc = frappe.db.get_list(
        'Employee Checkin',
        fields=['name', 'employee_name', 'log_type', 'time','device_id','employee','skip_auto_attendance',"creation"],
        filters={'employee': ['like', f'%{employee_id}%']},
        order_by='creation desc',
        limit_start=limit_start,
        limit_page_length=limit_page_length
    )
        return doc


    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_attendance_details API Error")
        return {
            "success": False,
            "message": f"An error occurred while fetching attendance: {str(e)}",
            "data": []
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
        limit=1
    )
    if sa:
        return sa[0].shift_type, sa[0].shift_location
    return frappe.db.get_value("Employee", employee, "default_shift"), None


def get_shift_tz_for_location(shift_location):
    """Get timezone for shift location"""
    if shift_location == "Beirut, Lebanon":
        return pytz.timezone("Asia/Beirut")
    elif shift_location == "Riyadh, Saudi Arabia":
        return pytz.timezone("Asia/Riyadh")
    return pytz.UTC


from frappe.utils import getdate, get_time, flt, now_datetime
@frappe.whitelist()
def get_log_type(employee, punch_time,log_type):
    """Determine log type (IN, OUT, Late Entry, Early Exit considering shift)"""
    punch_dt = punch_time

    shift_type, shift_location = get_shift_info(employee)



    if not shift_type:
        return "IN" if log_type == "IN" else "OUT"

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

    return "IN"





def employee_checkin_handler(doc, method):
    if doc.log_type in ["OUT", "Early Exit"]:
        frappe.db.set_value("Employee", doc.employee, "custom_in", 0)
