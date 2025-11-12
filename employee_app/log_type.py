import frappe
def execute():
    frappe.db.set_value(
        "DocField",
        {"parent": "Employee Checkin", "fieldname": "log_type"},
        "options",
        "IN\nOUT\nLate Entry\nEarly Exit"
    )