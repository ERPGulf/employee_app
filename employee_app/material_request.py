import frappe
import json
from werkzeug.wrappers import Response, Request
from erpnext.stock.utils import get_stock_balance
import base64
from datetime import datetime, timedelta
from frappe.utils import now_datetime

from frappe import _
from frappe.utils.data import add_to_date, get_time, getdate
from erpnext import get_region
from pyqrcode import create as qr_create
from base64 import b64encode
import io
import os
from base64 import b64encode
from frappe.model.mapper import get_mapped_doc
from frappe.utils import getdate, get_time, flt, now_datetime

from frappe.utils import cint

@frappe.whitelist(allow_guest=True)
def warehouse_list(employee_code=None):
    """
    Returns a list of warehouses.
    """
    try:

        employee_doc=frappe.get_doc("Employee",employee_code)
        warehouse_name=employee_doc.custom_stocker_warehouse
        warehouse_list = frappe.get_all(
            "Warehouse",
            fields=[
                "name as warehouse_id",
                "warehouse_name",
            ],
            filters={"name": warehouse_name},
        )


        return Response(
            json.dumps({"data": warehouse_list}),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json",
        )


@frappe.whitelist(allow_guest=True)
def get_items(item_code=None, uom=None, barcode=None, warehouse=None):
    try:

        if barcode:
            barcode_doc = frappe.get_value(
                "Item Barcode",
                {"barcode": barcode},
                ["parent", "uom"],
                as_dict=True
            )

            if not barcode_doc:
                return Response(
                    json.dumps({"error": "No item found for given barcode"}),
                    status=404,
                    mimetype="application/json"
                )

            item_code = barcode_doc.parent
            uom = barcode_doc.uom


        if not item_code or not uom:
            return Response(
                json.dumps({"error": "Either barcode or item_code & uom must be provided"}),
                status=400,
                mimetype="application/json"
            )


        item = frappe.get_value(
            "Item",
            item_code,
            ["name", "item_code", "item_name"],
            as_dict=True
        )

        if not item:
            return Response(
                json.dumps({"error": "Item not found with given item_code"}),
                status=404,
                mimetype="application/json"
            )


        total_qty = frappe.db.sql("""
            SELECT COALESCE(SUM(actual_qty), 0)
            FROM `tabBin`
            WHERE item_code = %s AND warehouse = %s
        """, (item_code, warehouse))[0][0]

        result = {
            "item_id": item.name,
            "item_name": item.item_name,
            "uom": uom,
            "total_qty": total_qty,
            "shelf_qty": total_qty
        }

        return Response(
            json.dumps({"data": result}, default=str),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_items API Error")
        return Response(
            json.dumps({"error": str(e) or "Unknown error"}),
            status=500,
            mimetype="application/json"
        )


@frappe.whitelist(allow_guest=True)
def create_stock_entry(item_id, date_time, warehouse, uom, qty, employee, branch=None, barcode=None, shelf=None):
    try:
        date_only = getdate(date_time)
        time_only = date_time.split(" ")[1] if " " in date_time else "00:00:00"

        frappe.set_user("Administrator")
        item_code = frappe.db.get_value("Item", {"name": item_id}, "name")
        if not item_code:
            return Response(
                json.dumps({
                    "status": "error",
                    "message": f"Item with name '{item_id}' does not exist."
                }),
                status=404,
                mimetype="application/json"
            )


        bin_val_rate = frappe.db.sql("""
            SELECT valuation_rate
            FROM `tabBin`
            WHERE item_code = %s AND warehouse = %s AND actual_qty > 0
            LIMIT 1
        """, (item_code, warehouse))

        if bin_val_rate:
            bin_val_rate = bin_val_rate[0][0]
        else:

            bin_val_rate = frappe.db.sql("""
                SELECT valuation_rate
                FROM `tabBin`
                WHERE item_code = %s AND actual_qty > 0
                ORDER BY creation DESC
                LIMIT 1
            """, (item_code,))
            bin_val_rate = bin_val_rate[0][0] if bin_val_rate else None


        if not bin_val_rate:
            bin_val_rate = frappe.db.get_value("Item", item_code, "last_purchase_rate")

        uom1, qty1 = normalize_to_default_uom(item_code, uom, qty)

        setting_doc = frappe.get_doc("Stocker Stock Setting")
        live_reconciliation = setting_doc.live__reconciliation
        system_qty_result = frappe.db.sql(
            """
            SELECT qty_after_transaction
            FROM `tabStock Ledger Entry`
            WHERE item_code=%s AND warehouse=%s AND posting_datetime<=%s
            ORDER BY
                CAST(posting_date AS DATETIME) + CAST(posting_time AS TIME) DESC
            LIMIT 1;
            """,
            (item_code, warehouse, date_time)
        )
        system_qty = system_qty_result[0][0] if system_qty_result else 0




        doc = frappe.get_doc({
            "doctype": "Stocker Stock Entries",
            "warehouse": warehouse,
            "barcode": barcode,
            "branch": branch,
            "shelf": shelf,
            "date": date_time,
            "item_code": item_code,
            "uom": uom,
            "qty": qty,
            "system_qty": system_qty,
            "employee": employee
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        create_reconciliation = True
        if live_reconciliation == 1 and system_qty == qty1:
            create_reconciliation = False

        if live_reconciliation == 1 and create_reconciliation and bin_val_rate:
            items = [
                {
                    "item_code": item_code,
                    "qty": qty1,
                    "warehouse": warehouse,
                    "valuation_rate": flt(bin_val_rate),
                    "barcode": barcode,
                    "custom_stocker_id": doc.name
                }
            ]
            Reconciliation_doc = frappe.get_doc({
                "doctype": "Stock Reconciliation",
                "purpose": "Stock Reconciliation",
                "naming_series": "STK-.YY..MM.-",
                "cost_center": branch,
                "set_warehouse": warehouse,
                "set_posting_time": 1,
                "posting_date": date_only,
                "posting_time": time_only,
                "items": items
            })
            Reconciliation_doc.insert(ignore_permissions=True)
            Reconciliation_doc.submit()

            frappe.db.set_value(
                "Stocker Stock Entries", doc.name, "stock_reconciliation", 1
            )

        elif live_reconciliation == 1 and not bin_val_rate:

            frappe.log_error(
                f"No valuation rate found for Item {item_code} while creating reconciliation.",
                "Stock Reconciliation Skipped"
            )
        elif live_reconciliation == 0 and system_qty == qty1:
            frappe.db.set_value("Stocker Stock Entries", doc.name, "stock_reconciliation", 1)


        data = {
            "status": "success",
            "id": doc.name,
            "item_code": doc.item_code,
            "warehouse": doc.warehouse,
            "shelf": doc.shelf,
            "barcode": doc.barcode,
            "uom": doc.uom,
            "qty": doc.qty,
            "date": doc.date,
            "employee": doc.employee,
            "branch": doc.branch,
            "stock_reconciliation": 1 if (live_reconciliation == 1 and bin_val_rate) else 0
        }
        return Response(
            json.dumps({"data": data}),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_stock_entry Error")
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json"
        )



from datetime import date

@frappe.whitelist(allow_guest=True)
def list_stock_entries(warehouse=None, item_code=None, today_only=False):
    """
    Returns a list of Warehouse Stock Log entries, optionally filtered by warehouse, item_code, and today's date.
    """


    try:
        filters = {}
        if warehouse:
            filters["warehouse"] = warehouse
        if item_code:
            filters["item_code"] = item_code
        if today_only:

            start = datetime.combine(date.today(), datetime.min.time())
            end = datetime.combine(date.today(), datetime.max.time())
            filters["date"] = ["between", [start, end]]

        stock_entries = frappe.get_all(
            "Stocker Stock Entries",
            filters=filters,
            fields=[
                "name as entry_id",
                "warehouse",
                "item_code",
                "barcode",
                "shelf",
                "uom",
                "qty",
                "date"
            ],
            order_by="date desc"
        )

        return Response(
            json.dumps({"data": stock_entries}, default=str),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "list_stock_entries API Error")
        return Response(
            json.dumps({"error": str(e) or "Unknown error"}),
            status=500,
            mimetype="application/json"
        )





@frappe.whitelist(allow_guest=True)
def update_stock_entry(entry_id, warehouse=None, barcode=None, shelf=None, date=None, item_code=None, uom=None, qty=None):
    """
    Updates a Warehouse Stock Log entry by entry_id.
    """
    try:
        doc = frappe.get_doc("Stocker Stock Entries", entry_id)
        if warehouse is not None:
            doc.warehouse = warehouse
        if barcode is not None:
            doc.barcode = barcode
        if shelf is not None:
            doc.shelf = shelf
        if date is not None:
            doc.date = date
        if item_code is not None:
            doc.item_code = item_code
        if uom is not None:
            doc.uom = uom
        if qty is not None:
            doc.qty = qty

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        data = {
            "status": "success",
            "entry_id": doc.name,
            "warehouse": doc.warehouse,
            "barcode": doc.barcode,
            "shelf": doc.shelf,
            "date": doc.date,
            "item_code": doc.item_code,
            "uom": doc.uom,
            "qty": int(doc.qty)
        }
        return Response(
            json.dumps({"data": data}, default=str),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "update_stock_entry API Error")
        return Response(
            json.dumps({"error": str(e) or "Unknown error"}),
            status=500,
            mimetype="application/json"
        )





@frappe.whitelist(allow_guest=True)
def delete_stock_entry(entry_id):
    """
    Deletes a Warehouse Stock Log entry by entry_id.
    """
    try:
        frappe.delete_doc("Stocker Stock Entries", entry_id, ignore_permissions=True)
        frappe.db.commit()
        return Response(
            json.dumps({"status": "success", "message": f"Entry {entry_id} deleted"}),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "delete_stock_entry API Error")
        return Response(
            json.dumps({"error": str(e) or "Unknown error"}),
            status=500,
            mimetype="application/json"
        )




@frappe.whitelist(allow_guest=True)
def list_items(item_group=None, last_updated_time=None, pos_profile = None):


    try:
        fields = ["name", "stock_uom", "item_name", "item_group", "description", "modified","disabled"]
        # filters = {"item_group": ["like", f"%{item_group}%"]} if item_group else {}
        item_filters = {}
        if item_group:
            item_filters["item_group"] = ["like", f"%{item_group}%"]

        item_codes_set = set()

        if last_updated_time:
            try:
                last_updated_dt = datetime.strptime(last_updated_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return Response(
                    json.dumps(
                        {"error": "Invalid datetime format. Use YYYY-MM-DD HH:MM:SS"}
                    ),
                    status=400,
                    mimetype="application/json",
                )


            modified_item_filters = item_filters.copy()
            modified_item_filters["modified"] = [">", last_updated_dt]

            modified_items = frappe.get_all(
                "Item", fields=["name"], filters=modified_item_filters
            )
            item_codes_set.update([item["name"] for item in modified_items])


            price_items = frappe.get_all(
                "Item Price",
                fields=["item_code"],
                filters={"modified": [">", last_updated_dt]},
            )
            item_codes_set.update([p["item_code"] for p in price_items])

            if not item_codes_set:
                return Response(
                    json.dumps({"data": []}), status=200, mimetype="application/json"
                )

            item_filters["name"] = ["in", list(item_codes_set)]

        items = frappe.get_all("Item", fields=fields, filters=item_filters)
        item_meta = frappe.get_meta("Item")
        has_arabic = "custom_item_name_arabic" in [df.fieldname for df in item_meta.fields]
        has_english = "custom_item_name_in_english" in [
            df.fieldname for df in item_meta.fields
        ]

        grouped_items = {}

        for item in items:

            if item.disabled == 1:
                continue

            item_group_disabled = frappe.db.get_value(
                "Item Group", item.item_group, "custom_disabled"
            )


            if item.item_group not in grouped_items:
                grouped_items[item.item_group] = {
                    "item_group_id": item.item_group,
                    "item_group": item.item_group,
                    "item_group_disabled": bool(item_group_disabled),
                    "items": [] if not item_group_disabled else [],
                }

            if not item_group_disabled:
                item_doc = frappe.get_doc("Item", item.name)


                item_name_arabic = ""
                item_name_english = ""

                if has_arabic and item_doc.get("custom_item_name_arabic"):
                    item_name_arabic = item_doc.custom_item_name_arabic
                    item_name_english = item.item_name
                elif has_english and item_doc.get("custom_item_name_in_english"):
                    item_name_arabic = item.item_name
                    item_name_english = item_doc.custom_item_name_in_english

                uoms = frappe.get_all(
                    "UOM Conversion Detail",
                    filters={"parent": item.name},
                    fields=["name", "uom", "conversion_factor"],
                )

                barcodes = frappe.get_all(
                    "Item Barcode",
                    filters={"parent": item.name},
                    fields=["name", "barcode", "uom", "custom_editable_price", "custom_editable_quantity"],
                )

                price_list = "Retail Price"
                if pos_profile:
                    price_list = frappe.db.get_value(
                        "POS Profile", pos_profile, "selling_price_list"
                    ) or "Retail Price"

                item_prices = frappe.get_all(
                    "Item Price",
                    fields=["price_list_rate", "uom", "creation"],
                    filters={"item_code": item.name, "price_list": price_list},
                    order_by="creation",
                )

                price_map = {price.uom: price.price_list_rate for price in item_prices}
                barcode_map = {}
                for barcode in barcodes:
                    if barcode.uom in barcode_map:
                        barcode_map[barcode.uom].append(barcode.barcode)
                    else:
                        barcode_map[barcode.uom] = [barcode.barcode]

                grouped_items[item.item_group]["items"].append(
                    {
                        "item_id": item.name,
                        "item_code": item.name,
                        "item_name": item.item_name,
                        "item_name_english": item_name_english,
                        "item_name_arabic": item_name_arabic,
                        "tax_percentage": (item.get("custom_tax_percentage") or 0.0),
                        "description": item.description,
                        "barcodes": [
                            {
                                "id": barcode.name,
                                "barcode": barcode.barcode,
                                "uom": barcode.uom,
                            }
                            for barcode in barcodes
                        ],
                        "uom": [
                            {
                                "id": uom.name,
                                "uom": uom.uom,
                                "conversion_factor": uom.conversion_factor,
                                "price": round(price_map.get(uom.uom, 0.0), 2),
                                "barcode": ", ".join(barcode_map.get(uom.uom, [])),
                                "editable_price": bool(
                                    frappe.get_value("UOM", uom.uom, "custom_editable_price")
                                ),
                                "editable_quantity": bool(
                                    frappe.get_value("UOM", uom.uom, "custom_editable_quantity")
                                ),
                            }
                            for uom in uoms
                        ],
                    }
                )
        result = list(grouped_items.values())


        if not result:
            return Response(
            json.dumps({"error": "No items found"}),
            status=404,
            mimetype="application/json"
        )

        return Response(
            json.dumps({"data": result}),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        return Response(
            json.dumps({"error":e}),
            status=404,
            mimetype="application/json"
        )


def create_qr_code(doc, method):
    """Create QR Code after inserting Sales Inv"""


    if not hasattr(doc, 'custom_qr_code'):
        return

    fields = frappe.get_meta('Employee').fields

    for field in fields:
        if field.fieldname == 'custom_qr_code' and field.fieldtype == 'Attach Image':

            ''' TLV conversion for
            1. Company name
            2. Employee code
            3. Full Name
            4. User_ID
            5. API URL
            6. Payroll Cost Center
            '''
            tlv_array = []

            company_name = "Company: " + frappe.db.get_value('Company', doc.company, 'company_name')
            if not company_name:
                frappe.throw(_('Company name missing for {} in the company document'.format(doc.company)))

            tag = bytes([1]).hex()
            length = bytes([len(company_name.encode('utf-8'))]).hex()
            value = company_name.encode('utf-8').hex()
            tlv_array.append(''.join([tag, length, value]))

            user_name = "Employee_Code: " + str(doc.name)
            if not user_name:
                frappe.throw(_('Employee name missing for {} in the document'))

            tag = bytes([1]).hex()
            length = bytes([len(user_name.encode('utf-8'))]).hex()
            value = user_name.encode('utf-8').hex()
            tlv_array.append(''.join([tag, length, value]))

            full_name = "Full_Name: " + str(doc.first_name + "  " + doc.last_name)
            tag = bytes([1]).hex()
            length = bytes([len(full_name.encode('utf-8'))]).hex()
            value = full_name.encode('utf-8').hex()
            tlv_array.append(''.join([tag, length, value]))

            full_name = "User_id: " + str(doc.user_id)
            tag = bytes([1]).hex()
            length = bytes([len(full_name.encode('utf-8'))]).hex()
            value = full_name.encode('utf-8').hex()
            tlv_array.append(''.join([tag, length, value]))

            api_url = "API: " +  frappe.local.conf.host_name



            tag = bytes([1]).hex()
            length = bytes([len(api_url.encode('utf-8'))]).hex()
            value = api_url.encode('utf-8').hex()
            tlv_array.append(''.join([tag, length, value]))
            if doc.custom_stocker_branch:
                cost_center = "Payroll_Cost_Center: " + str(doc.custom_stocker_branch)
                tag = bytes([1]).hex()
                # llength = format(len(cost_center.encode('utf-8')), '02x')
                value = cost_center.encode('utf-8').hex()
                tlv_array.append(''.join([tag, length, value]))


            tlv_buff = ''.join(tlv_array)

            base64_string = b64encode(bytes.fromhex(tlv_buff)).decode()



            qr_image = io.BytesIO()
            url = qr_create(base64_string, error='L')
            url.png(qr_image, scale=2, quiet_zone=1)

            filename = f"QR-CODE-{doc.name}.png".replace(os.path.sep, "__")


            _file = frappe.get_doc({
                "doctype": "File",
                "file_name": filename,
                "content": qr_image.getvalue(),
                "is_private": 0
            })

            _file.save()

            doc.db_set('image', _file.file_url)


            doc.notify_update()

            break




def normalize_to_default_uom(item_code, uom, qty):
    qty = flt(qty)

    default_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    if not default_uom or not uom or uom == default_uom:
        return uom, qty


    conversion_factor = frappe.db.get_value(
        "UOM Conversion Detail",
        {"parent": item_code, "uom": uom},
        "conversion_factor"
    )

    if not conversion_factor:
        frappe.throw(
            f"Conversion factor for UOM {uom} not defined for Item {item_code}"
        )


    new_qty = qty * flt(conversion_factor)
    return default_uom, new_qty




@frappe.whitelist(allow_guest=True)
def make_stock_entry(source_name, filters=None):
    import json

    if isinstance(source_name, str):
        source_name = json.loads(source_name)

    if isinstance(filters, str):
        filters = json.loads(filters)

    raw_items = []

    if filters:
        docs = frappe.get_list(
            "Stocker Stock Entries",
            filters=filters,
            fields=["name", "item_code", "warehouse", "uom", "qty", "barcode", "shelf"]
        )
        for d in docs:
            date_only = getdate(d.date)
            time_only = get_time(d.date)
            d.uom, d.qty = normalize_to_default_uom(d.item_code, d.uom, d.qty)
            bin_val_rate1 = frappe.db.get_value(
                "Bin",
                {"item_code": d.item_code, "warehouse": d.warehouse},
                "valuation_rate"
            )
            if not bin_val_rate1:
                last_purchase_rate = frappe.db.get_value(
                    "Item", {"name": d.item_code}, "last_purchase_rate"
                )
                valuation_rate = flt(last_purchase_rate) if last_purchase_rate else 0
            else:
                valuation_rate = flt(bin_val_rate1)

            raw_items.append({
                "item_code": d.item_code,
                "warehouse": d.warehouse,
                "uom": d.uom,
                "qty": d.qty,
                "barcode": d.barcode,
                "shelf": d.shelf,
                "posting_date":date_only,
                "posting_time": time_only,
                "valuation_rate": valuation_rate,
            })
    else:
        for name in source_name:
            doc = frappe.get_doc("Stocker Stock Entries", name)
            date_only = getdate(doc.date)
            time_only = get_time(doc.date)
            uom, qty = normalize_to_default_uom(doc.item_code, doc.uom, doc.qty)
            bin_val_rate = frappe.db.get_value(
                "Bin",
                {"item_code": doc.item_code, "warehouse": doc.warehouse},
                "valuation_rate"
            )
            if not bin_val_rate:
                last_purchase_rate = frappe.db.get_value(
                    "Item", {"name": doc.item_code}, "last_purchase_rate"
                )
                valuation_rate = flt(last_purchase_rate) if last_purchase_rate else 0
            else:
                valuation_rate = flt(bin_val_rate)

            raw_items.append({
                "custom_stocker_id":doc.name,
                "item_code": doc.item_code,
                "warehouse": doc.warehouse,
                "uom": uom,
                "qty": qty,
                "barcode": getattr(doc, "barcode", None),
                "shelf": getattr(doc, "shelf", None),
                "posting_date":date_only,
                "posting_time": time_only,
                "valuation_rate": valuation_rate,
            })


    merged = {}
    for item in raw_items:
        key = (item["item_code"], item["warehouse"], item["uom"],item["posting_date"])
        if key not in merged:
            merged[key] = item
        else:
            merged[key]["qty"] += item["qty"]

    return list(merged.values())




@frappe.whitelist(allow_guest=True)
def get_item_uom(item_code):
    try:

        doc = frappe.get_doc("Item", item_code)


        uom_list = [uom.uom for uom in doc.uoms]
        return Response(
            json.dumps({"data": uom_list}),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        return Response(
            json.dumps({"data": e}),
            status=500,
            mimetype="application/json"
        )

@frappe.whitelist(allow_guest=True)
def list_items_search(item=None, limit=None, offset=0):
    try:
        filters = {}
        or_filters = {}

        if item:

            or_filters = {
                "name": ["like", f"%{item}%"],
                "item_name": ["like", f"%{item}%"]
            }

        items = frappe.get_all(
            "Item",
            fields=["item_code", "item_name", "item_group"],
            filters=filters,
            or_filters=or_filters,
            limit_page_length=limit,
            limit_start=offset
        )

        return Response(
            json.dumps({"data": items}),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json"
        )





@frappe.whitelist(allow_guest=True)
def on_submit(doc, method):
    for row in doc.items:
        if row.item_code and row.warehouse and doc.posting_date and doc.posting_time:
            item_code = frappe.db.get_value("Item", {"item_name":row.item_code}, "name")
            posting_datetime = f"{doc.posting_date} {doc.posting_time}"
            entries = frappe.get_all(
                "Stocker Stock Entries",
                filters={
                    "item_code": item_code,
                    "warehouse": row.warehouse,
                    "date": posting_datetime,
                    "stock_reconciliation": 0
                },
                fields=["name"]
            )
            for entry in entries:
                frappe.db.set_value(
                    "Stocker Stock Entries",
                    entry.name,
                    "stock_reconciliation",
                    1
                )


@frappe.whitelist()
def create_stock_reconciliation_doc(entries):


    entries = json.loads(entries)
    created_reconciliations = []

    for entry in entries:
        if isinstance(entry, dict):
            entry = entry.get("name")

        se_doc = frappe.get_doc("Stocker Stock Entries", entry)
        if se_doc.stock_reconciliation == 1:
            frappe.throw("This entry is already reconciled ")

        item_code = se_doc.item_code
        date_only = getdate(se_doc.date)
        time_only = get_time(se_doc.date)
        system_qty_result = frappe.db.sql(
            """
            SELECT qty_after_transaction
            FROM `tabStock Ledger Entry`
            WHERE item_code=%s AND warehouse=%s AND posting_datetime=%s
            ORDER BY
                CAST(posting_date AS DATETIME) + CAST(posting_time AS TIME) DESC
            LIMIT 1;
            """,
            (item_code, se_doc.warehouse, se_doc.date)
        )
        system_qty = system_qty_result[0][0] if system_qty_result else 0
        if se_doc.qty== system_qty:
            frappe.throw("This entry is already reconciled ")


        bin_val_rate = frappe.db.sql("""
            SELECT valuation_rate
            FROM `tabBin`
            WHERE item_code = %s AND warehouse = %s AND actual_qty > 0
            LIMIT 1
        """, (item_code, se_doc.warehouse))

        if bin_val_rate:
            bin_val_rate = bin_val_rate[0][0]
        else:

            bin_val_rate = frappe.db.sql("""
                SELECT valuation_rate
                FROM `tabBin`
                WHERE item_code = %s AND actual_qty > 0
                ORDER BY creation DESC
                LIMIT 1
            """, (item_code,))

            bin_val_rate = bin_val_rate[0][0] if bin_val_rate else None

        if not bin_val_rate:
            last_purchase_rate = frappe.db.get_value("Item", item_code, "last_purchase_rate")

        final_rate = flt(bin_val_rate) or flt(last_purchase_rate) or flt(se_doc.valuation_rate)


        if not final_rate:
            frappe.throw(
                f"No valuation rate found for Item {item_code} in warehouse {se_doc.warehouse} "
                f"and Stock Entry {se_doc.name}."
            )


        uom1, qty1 = normalize_to_default_uom(item_code, se_doc.uom, se_doc.qty)


        recon_doc = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "purpose": "Stock Reconciliation",
            "naming_series":"STK-.YY..MM.-",
            "posting_date": date_only,
            "posting_time": time_only,
            "set_warehouse": se_doc.warehouse,
            "set_posting_time": 1,
            "items": [{
                "item_code": item_code,
                "warehouse": se_doc.warehouse,
                "qty": qty1,
                "valuation_rate": final_rate,
                "barcode": se_doc.barcode,
                "custom_stocker_id": se_doc.name
            }]
        })

        recon_doc.insert(ignore_permissions=True)
        recon_doc.submit()
        frappe.db.set_value("Stocker Stock Entries", se_doc.name, "stock_reconciliation", 1)
        created_reconciliations.append(recon_doc.name)

    return ", ".join(created_reconciliations)


@frappe.whitelist(allow_guest=True)
def get_stock(item_code, warehouse, to):
    return frappe.db.sql(
        """
        SELECT qty_after_transaction, valuation_rate
        FROM `tabStock Ledger Entry`
        WHERE item_code=%s AND warehouse=%s AND posting_datetime<=%s
        ORDER BY
            CAST(posting_date AS DATETIME) + CAST(posting_time AS TIME) DESC
        LIMIT 1;
        """,
        (item_code, warehouse, to),
        as_dict=True
    )

