import frappe
from frappe.model.document import Document
from frappe.utils import getdate, time_diff_in_hours, add_to_date

MAX_BREAK_HOURS = 2

class EmployeeBreak(Document):

    def after_insert(self):
        log_date = getdate(self.time)

        # 🔹 Find OPEN break
        open_break = frappe.db.get_value(
            "Break Application",
            {
                "employee": self.employee,
                "date": log_date,
                "time_out": ["is", "not set"],
                "docstatus": ["!=", 2]
            },
            order_by="creation desc"
        )


        if self.log_type == "IN":

            total_today = self.get_total_break_hours(log_date)
            frappe.log_error("total", total_today)


            self.validate_break_on_in(total_today)

            break_app = frappe.get_doc({
                "doctype": "Break Application",
                "employee": self.employee,
                "date": log_date,
                "time_in": self.time,
                "company": frappe.db.get_value("Employee", self.employee, "company")
            })
            break_app.insert(ignore_permissions=True)


        elif self.log_type == "OUT":

            if not open_break:
                frappe.throw("No active break found. Please log IN first.")

            break_app = frappe.get_doc("Break Application", open_break)


            current_hours = time_diff_in_hours(self.time, break_app.time_in)

            total_previous = self.get_total_break_hours(
                log_date, exclude=open_break
            )


            final_to_time, final_hours = self.validate_break_on_out(
                break_app.time_in,
                self.time,
                total_previous,
                current_hours
            )


            break_app.time_out = final_to_time
            break_app.total_break_hours = final_hours
            break_app.save(ignore_permissions=True)

    def validate_break_on_in(self, total_today):
        """
        Prevent IN if daily break limit reached
        """
        if total_today >= MAX_BREAK_HOURS:
            frappe.throw("Your daily 2 hour break is already completed.")

    def validate_break_on_out(self, from_time, to_time, total_previous, current_hours):
        """
        Validate total break hours and auto-adjust if exceeded
        Returns: (final_to_time, final_hours)
        """

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


    def get_total_break_hours(self, log_date, exclude=None):
        """
        Get total completed break hours for a day
        """

        filters = {
            "employee": self.employee,
            "date": log_date,
            "time_out": ["is", "set"],
            "docstatus": ["!=", 2]
        }

        if exclude:
            filters["name"] = ["!=", exclude]

        breaks = frappe.get_all(
            "Break Application",
            filters=filters,
            fields=["total_break_hours"]
        )

        return sum((b.total_break_hours or 0) for b in breaks)