frappe.pages['asset-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Maintenance-Dashboard',
		single_column: true
	});
}