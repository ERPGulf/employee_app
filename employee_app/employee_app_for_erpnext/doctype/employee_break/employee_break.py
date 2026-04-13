import frappe
from frappe.model.document import Document
from frappe.utils import getdate, time_diff_in_hours, add_to_date

MAX_BREAK_HOURS = 2


class EmployeeBreak(Document):

    def after_insert(self):
        log_date = getdate(self.time)

        if self.log_type == "IN":

            total_today = self.get_total_break_hours(log_date)
            self.validate_break_on_in(total_today)


            return

        elif self.log_type == "OUT":


            last_in = frappe.get_all(
                "Employee Break",
                filters={
                    "employee": self.employee,
                    "log_type": "IN",
                    "time": ["<=", self.time]
                },
                fields=["name", "time"],
                order_by="time desc",
                limit=1
            )

            if not last_in:
                frappe.throw("No IN log found before OUT.")

            in_time = last_in[0].time


            existing_break = frappe.db.exists(
                "Break Application",
                {
                    "employee": self.employee,
                    "date": log_date,
                    "time_in": in_time
                }
            )

            if existing_break:
                frappe.throw("Break already recorded for this IN time.")


            current_hours = time_diff_in_hours(self.time, in_time)

            total_previous = self.get_total_break_hours(log_date)


            final_to_time, final_hours = self.validate_break_on_out(
                in_time,
                self.time,
                total_previous,
                current_hours
            )


            break_app = frappe.get_doc({
                "doctype": "Break Application",
                "employee": self.employee,
                "date": log_date,
                "time_in": in_time,
                "time_out": final_to_time,
                "total_break_hours": final_hours,
                "company": frappe.db.get_value("Employee", self.employee, "company")
            })

            break_app.insert(ignore_permissions=True)


    def validate_break_on_in(self, total_today):
        if total_today >= MAX_BREAK_HOURS:
            frappe.throw("Your daily 2 hour break is already completed.")


    def validate_break_on_out(self, from_time, to_time, total_previous, current_hours):

        total_today = total_previous + current_hours

        if total_today > MAX_BREAK_HOURS:
            remaining_hours = MAX_BREAK_HOURS - total_previous

            adjusted_to_time = add_to_date(
                from_time,
                hours=remaining_hours
            )

            frappe.msgprint(
                f"Break limit exceeded. Auto closed at {adjusted_to_time}"
            )

            return adjusted_to_time, remaining_hours

        return to_time, current_hours


    def get_total_break_hours(self, log_date):

        breaks = frappe.get_all(
            "Break Application",
            filters={
                "employee": self.employee,
                "date": log_date,
                "time_out": ["is", "set"],
                "docstatus": ["!=", 2]
            },
            fields=["total_break_hours"]
        )
        return sum((b.total_break_hours or 0) for b in breaks)