import frappe
import json


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
    
    
# API for vehicle no and odometer
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
def employee_checkin(employee_name):
    doc=frappe.db.get_list('Employee Checkin',fields=['log_type','time','employee'],filters={'employee_name':['like',f'{employee_name}']},limit_start=0,limit_page_length=10)
    return doc
    
     


        






    





