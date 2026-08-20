import frappe
from frappe import _

FIELD = "custom_employee_location1"
LINK_FIELD = "location"
LINK_TO = "Employee Location"


@frappe.whitelist()
def set_employee_locations(names, values, mode="replace"):
    names = frappe.parse_json(names)
    values = frappe.parse_json(values)

    if not names or not values:
        frappe.throw(_("Nothing to update"))

    df = frappe.get_meta("Employee").get_field(FIELD)
    if not df or df.fieldtype not in ("Table", "Table MultiSelect"):
        frappe.throw(_("{0} is not a child table field").format(FIELD))

    values = list(dict.fromkeys(values))

    missing = [v for v in values if not frappe.db.exists(LINK_TO, v)]
    if missing:
        frappe.throw(_("These do not exist in {0}: {1}").format(
            LINK_TO, ", ".join(missing)))

    for name in names:
        if not frappe.has_permission("Employee", "write", doc=name):
            frappe.throw(_("No write permission on {0}").format(name))

    if len(names) > 30:
        frappe.enqueue(
            _apply, queue="long", timeout=3600, names=names,
            values=values, mode=mode, link_field=LINK_FIELD,
            user=frappe.session.user,
        )
        return {"queued": True, "count": len(names)}

    return {"queued": False, "count": _apply(names, values, mode, LINK_FIELD)}


def _apply(names, values, mode, link_field, user=None):
    done = 0
    for i, name in enumerate(names, 1):
        try:
            doc = frappe.get_doc("Employee", name)
            existing = [r.get(link_field) for r in doc.get(FIELD)]

            if mode == "replace":
                doc.set(FIELD, [])
                target = values
            elif mode == "append":
                target = [v for v in values if v not in existing]
            elif mode == "remove":
                keep = [r for r in doc.get(FIELD) if r.get(link_field) not in values]
                doc.set(FIELD, [])
                target = [r.get(link_field) for r in keep]
            else:
                frappe.throw(_("Bad mode"))

            for v in target:
                doc.append(FIELD, {link_field: v})

            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)
            done += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"bulk location: {name}")

        if i % 25 == 0:
            frappe.db.commit()

    frappe.db.commit()

    if user:
        frappe.publish_realtime(
            "msgprint", {"message": _("Updated {0} employees").format(done)},
            user=user,
        )
    return done