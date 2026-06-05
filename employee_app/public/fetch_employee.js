frappe.ui.form.on('Employee Notification', {
    refresh(frm) {
        frm.add_custom_button(__('Fetch Employees'), function () {

            if (!frm.doc.topic) {
                frappe.msgprint(__('Please enter Topic or Token'));
                return;
            }

            frappe.call({
                method: 'employee_app.attendance_api.get_notification1',
                args: {
                    value: frm.doc.topic
                },
                callback: function (r) {
                    if (!r.message) return;

                    // Clear existing rows
                    frm.clear_table('employee');

                    let employee_ids = r.message.employee_ids || [];

                    employee_ids.forEach(emp => {
                        let row = frm.add_child('employee');
                        row.employee = emp;
                    });

                    frm.refresh_field('employee');

                    frappe.msgprint(
                        __('{0} employee(s) fetched', [employee_ids.length])
                    );
                }
            });
        });
    }
});