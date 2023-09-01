import frappe

@frappe.whitelist(allow_guest=True)
def insert_new_trip(employee_id, trip_start_time, trip_start_km,trip_status,trip_start_location = None,job_order=None, trip_type=None, vehicle_number=None):
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
            "custom_trip_status": trip_status
        })
        doc.insert()
        frappe.db.commit()
        return doc
    except Exception as e:
        return e

@frappe.whitelist(allow_guest=True)
def close_the_trip(trip_id, trip_end_km=None, trip_end_location=None, trip_status=None, trip_end_time=None):
    try:
        doc = frappe.get_doc("driver trips", trip_id)
        doc.trip_end_time = trip_end_time
        doc.trip_ending_km = trip_end_km
        doc.trip_end_location = trip_end_location
        doc.custom_trip_status = trip_status
        doc.save()
        frappe.db.commit()
        return doc
    except Exception as e:
        return e

@frappe.whitelist(allow_guest=True)
def get_latest_open_trip(employee_id):
    try:
        doc = frappe.get_doc("driver trips", {"employee_id": employee_id, "custom_trip_status": True}, ["name", "trip_start_time", "trip_starting_km", "trip_start_location", "custom_job_order", "custom_trip_type", "vehicle_number", "trip_status"], order_by="creation desc")
        return doc
    except Exception as e:
        return "No Open Trip Found"
    
@frappe.whitelist(allow_guest=True)
def testoutput():
    return "Hello how are you"



@frappe.whitelist(allow_guest=True)
def get_all_contract(party_type=None,party_name=None,start_date=None,end_date=None,contract_terms=None):
    try:
        doc = frappe.get_doc("Contract")
        doc.party_type: party_type
        doc.party_name: party_name
        doc.start_date: start_date
        doc.end_date: end_date
        doc.contract_terms: contract_terms
        doc.save()
        frappe.db.commit()
        return doc
    except Exception as e:
        return e


