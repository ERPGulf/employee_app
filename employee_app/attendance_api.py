import frappe

@frappe.whitelist(allow_guest=True)
def insert_new_trip(employee_id, trip_start_time, trip_end_time,trip_start_location = None,trip_end_location=None):
    try:
        doc = frappe.get_doc({
            "doctype": "driver trips",
            "employee_id": employee_id,
            "trip_start_time": trip_start_time,
            "trip_end_time": trip_end_time,
            "trip_start_location": trip_start_location,
            "trip_end_location": trip_end_location,
        })
        doc.insert()
        frappe.db.commit()
        return doc
    except Exception as e:
        return e
    



