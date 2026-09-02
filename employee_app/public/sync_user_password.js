frappe.ui.form.on('User', {
    before_save: function (frm) {
        if (frm.doc.new_password) {
            frappe.call({
                method: 'employee_app.authentication.sync_user_password_to_employee',
                args: {
                    user: frm.doc.name,
                    password: frm.doc.new_password
                }
            });
        }
    }
});
