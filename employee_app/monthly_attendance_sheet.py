# Override of HRMS "Monthly Attendance Sheet" execute: Company filter optional (all companies when empty)
import frappe
from frappe import _
from frappe.utils import getdate
from frappe.utils.nestedset import get_descendants_of


def execute(filters=None):
	from hrms.hr.report.monthly_attendance_sheet import monthly_attendance_sheet as mas
	from hrms.utils import date_diff

	filters = frappe._dict(filters or {})

	if not filters.filter_based_on:
		frappe.throw(_("Please select Filter Based On"))

	if filters.filter_based_on == "Month" and not (filters.month and filters.year):
		frappe.throw(_("Please select month and year."))

	if filters.filter_based_on == "Date Range":
		if not (filters.start_date and filters.end_date):
			frappe.throw(_("Please set the date range."))
		if getdate(filters.start_date) > getdate(filters.end_date):
			frappe.throw(_("Start date cannot be greater than end date."))
		if date_diff(filters.end_date, filters.start_date) > 90:
			frappe.throw(_("Please set a date range less than 90 days."))

	# Company is optional: no company selected -> all companies
	if filters.company:
		filters.companies = [filters.company]
		if filters.include_company_descendants:
			filters.companies.extend(get_descendants_of("Company", filters.company))
	else:
		filters.companies = frappe.get_all("Company", pluck="name")

	attendance_map = mas.get_attendance_map(filters)
	if not attendance_map:
		frappe.msgprint(_("No attendance records found."), alert=True, indicator="orange")
		return [], [], None, None

	columns = mas.get_columns(filters)
	data = mas.get_data(filters, attendance_map)

	if not data:
		frappe.msgprint(_("No attendance records found for this criteria."), alert=True, indicator="orange")
		return columns, [], None, None

	message = mas.get_message() if not filters.summarized_view else ""
	chart = mas.get_chart_data(attendance_map, filters)

	return columns, data, message, chart


def apply():
	try:
		from hrms.hr.report.monthly_attendance_sheet import monthly_attendance_sheet as mas
	except ImportError:
		return
	mas.execute = execute
