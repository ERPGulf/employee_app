// Override for HRMS "Monthly Attendance Sheet" report filters.
// Company is no longer mandatory and has no default, so the report shows
// all employees until a company is selected. HRMS source stays untouched:
// we intercept the assignment of frappe.query_reports["Monthly Attendance Sheet"].
(() => {
	const REPORT = "Monthly Attendance Sheet";

	const patch = (report) => {
		(report?.filters || []).forEach((f) => {
			if (f.fieldname === "company") {
				f.reqd = 0;
				f.default = "";
			}
		});
		return report;
	};

	frappe.query_reports = frappe.query_reports || {};
	let value = frappe.query_reports[REPORT] && patch(frappe.query_reports[REPORT]);

	Object.defineProperty(frappe.query_reports, REPORT, {
		configurable: true,
		enumerable: true,
		get: () => value,
		set: (v) => {
			value = patch(v);
		},
	});
})();
