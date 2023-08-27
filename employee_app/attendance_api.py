import frappe

@frappe.whitelist(allow_guest=True)
def insert_new_trip(employee_id, trip_start_time, trip_start_km,trip_start_location = None,job_order=None, trip_type=None, vehicle_number=None, trip_status=None):
    try:
        doc = frappe.get_doc({
            "doctype": "driver trips",
            "employee_id": employee_id,
            "trip_start_time": trip_start_time,
            "trip_starting_km": trip_start_km,
            "trip_start_location": trip_start_location,
            "custom_job_order": job_order,
            "custom_trip_type": trip_type,
            "vehicle_number": vehicle_number,
            "trip_status": trip_status
        })
        doc.insert()
        frappe.db.commit()
        return doc
    except Exception as e:
        return e
    



