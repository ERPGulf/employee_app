frappe.listview_settings["Employee"] = frappe.listview_settings["Employee"] || {};

frappe.listview_settings["Employee"].onload = function (listview) {
    listview.page.add_actions_menu_item(
        __("Set Employee Location"),
        () => open_location_dialog(listview),
        false
    );
};

function open_location_dialog(listview) {
    const names = listview.get_checked_items(true);
    if (!names.length) {
        frappe.msgprint(__("Select at least one Employee"));
        return;
    }

    const d = new frappe.ui.Dialog({
        title: __("Set Employee Location ({0} records)", [names.length]),
        fields: [
            {
                fieldname: "mode",
                label: __("Mode"),
                fieldtype: "Select",
                options: [
                    { value: "replace", label: __("Replace existing") },
                    { value: "append", label: __("Add to existing") },
                    { value: "remove", label: __("Remove these") },
                ],
                default: "replace",
                reqd: 1,
            },
            {
                fieldname: "values",
                label: __("Location"),
                fieldtype: "MultiSelectList",
                reqd: 1,
                get_data: (txt) =>
                    frappe.db.get_link_options("Employee Location", txt),
            },
        ],
        primary_action_label: __("Update"),
        primary_action(v) {
            d.hide();
            frappe.call({
                method:
                    "employee_app.bulk_location.set_employee_locations",
                args: { names, values: v.values, mode: v.mode },
                freeze: true,
                freeze_message: __("Updating..."),
                callback: (r) => {
                    if (!r.message) return;
                    if (r.message.queued) {
                        frappe.show_alert({
                            message: __("Queued {0} records", [
                                r.message.count,
                            ]),
                            indicator: "blue",
                        });
                    } else {
                        frappe.show_alert({
                            message: __("Updated {0} records", [
                                r.message.count,
                            ]),
                            indicator: "green",
                        });
                        listview.refresh();
                    }
                },
            });
        },
    });
    d.show();
}