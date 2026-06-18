## Employee app for ERPNext

Attendance and related submissions through mobile APP.

- **App name:** `employee_app`
- **Publisher:** ERPGulf.com
- **Required apps:** `hrms`
- **License:** MIT

All endpoints below are Frappe whitelisted methods and are called as:

```
POST/GET https://<site>/api/method/<dotted.path.to.function>
```

Unless noted as `allow_guest=True`, a valid session/OAuth token is required (see [Authentication](#authentication--gauthpy)).

---

## Table of Contents

1. [Authentication — `gauth.py`](#authentication--gauthpy)
2. [Attendance & Employee APIs — `attendance_api.py`](#attendance--employee-apis--attendance_apipy)
3. [Material Request / Stock APIs — `material_request.py`](#material-request--stock-apis--material_requestpy)
4. [Document Event Hooks](#document-event-hooks)
5. [Known Issues](#known-issues)

---

## Authentication — `gauth.py`

Wraps Frappe's OAuth2 password-grant flow for the `MobileAPP` OAuth Client.

### `employee_app.gauth.generate_token_secure`
- **Auth:** `allow_guest=True`
- **Params:** `api_key` (username), `api_secret` (password), `app_key` (base64-encoded OAuth Client `app_name`, e.g. `MobileAPP`)
- **Behavior:** Decodes `app_key`, looks up the matching `OAuth Client`, then performs a password-grant request to `frappe.integrations.oauth2.get_token` using that client's `client_id`/`client_secret`.
- **Returns:** `{"data": {access_token, refresh_token, expires_in, ...}}` (200) or an error message (401/500).

### `employee_app.gauth.generate_custom_token_for_employee`
- **Auth:** requires login
- **Params:** `password`
- **Behavior:** Looks up the `MobileAPP` OAuth Client's configured user (`client_user`) and requests a token using that user as the OAuth `username` with the given `password`.
- **Returns:** Token JSON (200) or `{"message": "OAuth client not found"}` (401).

### `employee_app.gauth.create_refresh_token`
- **Auth:** `allow_guest=True`
- **Params:** `refresh_token`
- **Behavior:** Exchanges a refresh token for a new access token via `frappe.integrations.oauth2.get_token`.
- **Returns:** `{"data": {access_token, expires_in, token_type, scope, refresh_token}}` (200) or error (401/500).

### `employee_app.gauth.whoami`
- **Auth:** requires login
- **Params:** none
- **Returns:** `frappe.session.user` for the current token/session.

### `employee_app.gauth.generate_custom_token`
- **Auth:** requires login
- **Params:** `username`, `password`
- **Status:** Disabled — always returns `{"message": "Can not be used for production environmet"}` (500). The real implementation is commented out (dev/testing only).

### `employee_app.gauth.getToken2`
- Placeholder, no-op. Returns `None`.

### `employee_app.gauth.create_attendence_request`
- **Auth:** requires login (`allow_guest=False`)
- **Params:** `employee`, `from_date`, `to_date`, `from_time`, `to_time`, `reason`
- **Validation:** `from_date`/`to_date` cannot be in the future; `from_date` cannot be after `to_date`.
- **Behavior:** Creates an `Attendance Request` document (`custom_from_time`/`custom_to_time` store the time range).
- **Returns:** Created request details (200) or a validation/error message (400/500).

### `employee_app.gauth.validate_location_restriction` (whitelisted signature, see [Known Issues](#known-issues))
- **Auth:** requires login (`allow_guest=False`)
- **Params:** `employee`, `latitude`, `longitude`
- **Behavior:** Placeholder bounds check (`10 <= lat <= 50`, `60 <= lng <= 100`).
- ⚠️ **Not actually reachable as an API** — see Known Issues.


### Employee Checkin / Attendance

| Method | Params | Description |
|---|---|---|
| `employee_checkin` | `employee_code, limit_start, limit_page_length` | Lists `Employee Checkin` records (name, log type, time) matching `employee_code`, newest first. |
| `Employee_Checkin` | `employee_checkin, fieldname=None, fieldvalue=None, limit_start=0, limit_page_length=10` | If `fieldname`/`fieldvalue` given, updates that field on the matching checkin(s) first; always returns a filtered/paginated list of checkins. |
| `add_log_based_on_employee_field` | `employee_field_value, timestamp, location=None, device_id=None, log_type=None` | Creates an `Employee Checkin`. Resolves `log_type` via `get_log_type` (shift-aware). If the employee has `custom_unrestricted_checkout_location` enabled, validates `location` against the employee's allowed `Employee Location Child Table` rows; otherwise reverse-geocodes coordinates to a Google Maps "compound code" for the unrestricted location field. |
| `get_attendance_details` | `employee_id=None, limit_start=0, limit_page_length=20` | Paginated checkin history for an employee, newest first by `creation`. |
| `get_last_log` | `employee` | Returns the single most recent `Employee Checkin` for the employee. |
| `get_log_type` | `employee, punch_time, log_type` | Computes effective log type (`IN`, `OUT`, `Late Entry`, `Early Exit`) by comparing punch time to the employee's `Shift Type` grace periods. Returns `log_type` unchanged if shift tracking is disabled for the employee. |
| `is_employee_shift_enabled` | `employee=None` | Returns the employee's `custom_employee_shift` flag (0/1). |
| `employee_checkin_handler` *(doc event, not whitelisted)* | `doc, method` | On `Employee Checkin.after_insert`, sets `Employee.custom_in` to 0 for OUT/Early Exit or 1 for IN/Late Entry. |

### Working Hours / Breaks

| Method | Params | Description |
|---|---|---|
| `get_total_hours` | `employee, date` | Net worked time (`HH:MM`) for a calendar day = sum of IN→OUT checkin intervals minus break time, derived purely from `Employee Checkin`/`Employee Break` timestamps (no shift required). |
| `get_monthly_hours` | `employee, month, year` | Sums `get_total_hours` across every day of the given month, returned as `HH:MM`. |
| `get_employee_working_hours` | `employee, date` | Shift-aware working hours: finds the active `Shift Assignment`/`Shift Type` for the date, filters checkins to the shift window (handles overnight shifts), then delegates to HRMS's `calculate_working_hours`. Returns `0` if no shift assignment or no logs in the window. |
| `get_break_hours` | `employee, date` | Sum of IN→OUT `Employee Break` durations (hours) within the employee's shift window for that date. |
| `get_monthly_break_hours` | `employee, date` | Sums `get_break_hours` over every day of the month containing `date`. |
| `get_today_breaks` | `employee` | Returns today's individual break intervals (with `duration_minutes`) plus a running total; an unmatched `IN` is reported as `"status": "ongoing"`. |
| `Employee_break` | `employee_field_value, timestamp, location=None, device_id=None, log_type=None` | Creates an `Employee Break` entry. Rejects the request with a plain string message if the employee's monthly break total is already ≥ 8 hours. Links to the employee's last open checkin via `employee_checkin` if applicable. |
| `override_working_hours` *(doc event, not whitelisted)* | `doc, method` | On `Attendance.validate`: if the employee has any `Employee Break` entries that day, sets `custom_break_application_approved` based on an approved `Break Application`, and recomputes `working_hours` as `get_employee_working_hours - get_break_hours`. |

### Employee Profile / Dashboard

| Method | Params | Description |
|---|---|---|
| `employee` | `employee_code=None, custom_in=None` | No args → list all employee names. With `employee_code` only → full `Employee` doc. With `custom_in` (`0`/`1`) → updates `Employee.custom_in` and returns a confirmation set. |
| `get_employee_data` | `employee_id=None` | Returns employee summary (name, `custom_in`, restricted-location flag, unrestricted-checkout flag, photo) plus resolved `Employee Location` details (radius, lat/long) for each configured location row. 404 if not found. Without `employee_id`, returns all employee names. |
| `get_shortcut_1` / `get_shortcut_2` / `get_shortcut_3` | `employee` | Reads a configurable set of field labels from the singleton `Checkin App Setting` (`field1..field5` / `field21,field22,field32,field42,field52` / `field13,field23,field33,field34,field35`), scrubs them to fieldnames, validates they exist on `Employee`, then returns those field values for the given employee (used to drive configurable mobile-app dashboard shortcuts). |
| `qr_code` | `employee` | Returns a full URL (`host_name + custom_qr_code`) to the employee's QR code image, or an error if none is set. |
| `get_server_time` | — | Returns `{"server_time": <now>}`. |

### Notifications & Complaints

| Method | Params | Description |
|---|---|---|
| `get_notification` | `employee` | Looks up `Employee Table` child rows for the employee to find related `Employee Notification` parents, then returns those notifications (title, body, read flag, date, type), newest first. |
| `mark_notification_as_read` | `id` | Sets `Employee Notification.read = 1` (explicit `frappe.db.commit()`). |
| `get_notification1` | `value` *(allow_guest=True)* | Resolves an arbitrary push-notification "topic" or device token to employee id(s): first checks `Topic Table` for a topic match, falling back to `Employee.custom_token`. |
| `create_complaint` | `employee, date, message` *(allow_guest=True)* | Creates an `Employee Complaint` document. |

### Expense Claims & Leave

| Method | Params | Description |
|---|---|---|
| `get_expense_claims` | `employee=None, limit=100` | Flattens each `Expense Claim` into one row per expense line, joined with the claim's first attached file URL. |
| `create_expense_claim` | `employee, expense_date=None, amount=None, expense_type=None, description=None, file_name=None` | Creates an `Expense Claim` with one expense row. If files are present in the request, uploads them via `upload_file` and attaches to the new claim. Requires `employee`, `amount`, `expense_type`. |
| `create_leave_application` | `employee, leave_type, from_date, to_date, posting_date=None, acknowledgement_policy=None, reason=None` | Creates a `Leave Application` (`description` = reason, optional `custom_acknowledgement_policy1`). |

### File Upload

| Method | Params | Description |
|---|---|---|
| `upload_file` | (multipart form: files + `doctype`, `docname`, `fieldname`, `file_url`, `folder`, `method`, `file_name`, `is_private`, `optimize`, `max_width`, `max_height`) | Generic Frappe-style file upload handler. Supports guest uploads if `allow_guests_to_upload_files` system setting is on. Optionally optimizes images, attaches the file to a doctype/field, and can delegate entirely to an arbitrary whitelisted `method` instead of saving a `File` doc. |

---

## Material Request / Stock APIs — `material_request.py`

These power a barcode/warehouse "Stocker" mobile flow built on top of ERPNext Stock.

### Items & Warehouses

| Method | Params | Description |
|---|---|---|
| `warehouse_list` | `employee_code=None` *(allow_guest=True)* | Returns the single `Warehouse` configured on the employee's `custom_stocker_warehouse`. |
| `get_items` | `item_code=None, uom=None, barcode=None, warehouse=None` *(allow_guest=True)* | Resolves an item either directly (`item_code` + `uom`) or via `barcode` lookup (`Item Barcode`), then returns its current `Bin` quantity for `warehouse`. |
| `list_items` | `item_group=None, last_updated_time=None, pos_profile=None` *(allow_guest=True)* | Returns items grouped by item group, each with UOMs, conversion factors, per-UOM prices (from a POS profile's selling price list or "Retail Price"), barcodes, and Arabic/English name variants. If `last_updated_time` is given, restricts to items/prices modified after that timestamp (delta sync). Skips disabled items/groups. |
| `list_items_search` | `item=None, limit=None, offset=0` *(allow_guest=True)* | Type-ahead search over `item_name`/`item_code` prefix match. |
| `get_item_uom` | `item_code` *(allow_guest=True)* | Returns the list of UOMs defined on an item. |

### Stocker Stock Entries (mobile stock counts)

| Method | Params | Description |
|---|---|---|
| `create_stock_entry` | `item_id, date_time, warehouse, uom, qty, employee, branch=None, barcode=None, shelf=None` *(allow_guest=True)* | Creates a `Stocker Stock Entries` record capturing the system qty at that time (from `Stock Ledger Entry`) alongside the counted qty. If `Stocker Stock Setting.live__reconciliation` is enabled and the counted qty differs from system qty, immediately creates and submits a `Stock Reconciliation`. Runs as `Administrator`. |
| `list_stock_entries` | `warehouse=None, item_code=None, today_only=False` *(allow_guest=True)* | Lists `Stocker Stock Entries`, optionally filtered to today. |
| `update_stock_entry` | `entry_id, warehouse=None, barcode=None, shelf=None, date=None, item_code=None, uom=None, qty=None` *(allow_guest=True)* | Partial update of a `Stocker Stock Entries` record (only provided fields are changed). |
| `delete_stock_entry` | `entry_id` *(allow_guest=True)* | Deletes a `Stocker Stock Entries` record. |
| `create_stock_reconciliation_doc` | `entries` (JSON list of entry names or `{"name": ...}` objects) | Creates+submits one `Stock Reconciliation` per entry, using the best available valuation rate (`Bin` → last purchase rate → entry's stored rate). Throws if an entry is already reconciled or already matches system qty. |
| `make_stock_entry` | `source_name` (list of entry names, JSON), `filters=None` *(allow_guest=True)* | Builds (but does not insert) raw line items for a `Stock Entry`/mapped doc from one or more `Stocker Stock Entries`, normalizing quantities to the item's default UOM and merging duplicate item/warehouse/uom/date combinations. |
| `get_stock` | `item_code, warehouse, to` *(allow_guest=True)* | Returns the most recent `Stock Ledger Entry` qty/valuation at or before the `to` timestamp. |
| `on_submit` *(doc event, not whitelisted as a doc-event consumer despite the decorator)* | `doc, method` | Marks matching `Stocker Stock Entries` rows as reconciled when a document with stock items (e.g. a Stock Entry) is submitted. **Not currently wired into `hooks.py`'s `doc_events`** — see Known Issues. |

### Material Requests

| Method | Params | Description |
|---|---|---|
| `create_material_request` | `date, warehouse, items` (JSON list of `{item_code, qty, schedule_date, uom}`) | Creates a `Material Request` (`material_request_type="Purchase"`) with the given line items against `warehouse`. |
| `list_material_requests` | `id=None` | Returns all `Material Request` docs (or one, if `id` given) with their child items. |

### Other

| Method | Params | Description |
|---|---|---|
| `normalize_to_default_uom` *(helper, not whitelisted)* | `item_code, uom, qty` | Converts a qty from `uom` to the item's stock UOM using `UOM Conversion Detail`. |
| `create_qr_code` *(doc event, not whitelisted)* | `doc, method` | Generates a TLV-encoded QR code image (company, employee code, name, user id, API URL, cost center) and attaches it as the doc's `image`. Despite the docstring ("after inserting Sales Inv"), the logic inspects the `Employee` doctype's `custom_qr_code` field — **not wired into `hooks.py`'s `doc_events`**. |

---

## Document Event Hooks

Configured in [`hooks.py`](employee_app/hooks.py):

| Doctype | Event | Handler |
|---|---|---|
| `Employee Checkin` | `after_insert` | `employee_app.attendance_api.employee_checkin_handler` |
| `Attendance` | `validate` | `employee_app.attendance_api.override_working_hours` |
| `Employee Location` | `validate` | `employee_app.gauth.validate_coordinates` |

`validate_coordinates` enforces that latitude/longitude are both present or both absent, are valid decimal strings, and fall within `[-90, 90]` / `[-180, 180]` respectively.

An `Employee` block (QR code generation on update, cleanup on trash, location validation) exists in `hooks.py` but is **commented out**.

---

## Known Issues

- **`gauth.py` defines `validate_location_restriction` twice** — once as a whitelisted API (`employee, latitude, longitude`) and again a few lines later as a plain doc-event handler (`doc, method`). Because both share the same module-level name, the second definition silently replaces the first in `employee_app.gauth`'s namespace. Any call to `employee_app.gauth.validate_location_restriction` as an API will resolve to the `(doc, method)` version and fail (it isn't whitelisted and expects a document object, not `employee`/`latitude`/`longitude`). The doc-event version is also not currently referenced in `hooks.py`. One of the two should be renamed if both behaviors are needed.
- **`on_submit` (`material_request.py`)** and **`create_qr_code` (`material_request.py`)** are defined as document-event-style handlers but are not registered in `hooks.py`'s `doc_events`, so they currently have no effect unless wired up elsewhere (e.g. a Server Script) or invoked directly.
