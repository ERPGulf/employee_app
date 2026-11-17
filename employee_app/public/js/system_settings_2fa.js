// Copyright (c) 2026, ERPGulf.com
// System Settings: shows the locked Two-Factor Policy under the 2FA method.
// The policy is set in site_config.json by the ERPGulf backend team (employee_app/twofa.py).
frappe.ui.form.on("System Settings", {
    refresh(frm) {
        frappe.call("employee_app.twofa.policy_info").then((r) => {
            const policy = r.message;
            const text = {
                "Maximum: all users": __("Every user, system and website, must use two-factor sign-in. No exceptions."),
                "High: all system users": __(
                    "Every system user must use two-factor sign-in. Website users need it only if one of their roles requires it."
                ),
                "Standard: by role": __("Only users with a role that requires two-factor sign-in must use it."),
            }[policy];
            if (!text) return;

            const field = frm.get_field("two_factor_method");
            if (!field) return;
            field.$wrapper.find(".eg-2fa-policy").remove();
            field.$wrapper.append(
                `<div class="eg-2fa-policy text-muted" style="margin-top:14px;font-size:13px;line-height:1.6">
					<b>${__("Two-Factor Policy")}: ${frappe.utils.escape_html(policy)}</b>
					<span class="indicator-pill gray" style="margin-left:6px">${__("Managed by ERPGulf")}</span><br>
					${text}<br>
					${__("This cannot be changed here. To change it, contact ERPGulf support.")}
				</div>`
            );

            // Under High and Maximum, two-factor sign-in cannot be switched off here
            frm.set_df_property("enable_two_factor_auth", "read_only", policy === "Standard: by role" ? 0 : 1);
        });
    },
});