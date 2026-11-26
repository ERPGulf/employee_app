# Integration tests for add_offline_employee_checkins. They need a site with erpnext, hrms
# and employee_app installed, and Redis:
#   bench --site <test-site> run-tests --module employee_app.tests.test_offline_checkins
# They create Employee Checkin records: use a local or staging test site, never a client site.

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from employee_app.attendance_api import add_offline_employee_checkins

test_dependencies = ["Employee"]

DUPLICATE = "already has a log with the same timestamp"


class TestOfflineCheckins(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")  # the previous class may have left another user in session
        for patcher in (
            patch("employee_app.user_qa_code.create_qr_code"),  # QR files are not under test
            # The endpoint commits; keep everything in the test transaction that the class rolls back.
            patch.object(frappe.db, "commit"),
        ):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        cls.employee = frappe.get_doc({
            "doctype": "Employee", "naming_series": "EMP-", "first_name": "Offline", "gender": "Female",
            "date_of_birth": "1990-05-08", "date_of_joining": "2013-01-01", "company": "_Test Company",
            "status": "Active",
        }).insert().name

    def setUp(self):
        # The helper reads frappe.request.files after inserting, as it does in a real request.
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())
        self.addCleanup(setattr, frappe.local, "request", previous)

    def push(self, *timestamps):
        """Upload one queued record per timestamp, shaped as the app sends them."""
        response = add_offline_employee_checkins(logs=[
            {"employee": self.employee, "timestamp": ts, "device_id": "MobileAPP", "log_type": "IN", "over_time": 0}
            for ts in timestamps
        ])
        return response.status_code, json.loads(response.get_data())

    def checkins_at(self, timestamp):
        return frappe.get_all("Employee Checkin", filters={"employee": self.employee, "time": timestamp}, pluck="name")

    def test_new_record_is_inserted(self):
        status, body = self.push("2026-11-21 08:00:00")
        self.assertEqual(status, 200)
        self.assertEqual(body["inserted"], self.checkins_at("2026-11-21 08:00:00"))
        self.assertEqual(len(body["inserted"]), 1)

    def test_resent_record_is_refused_with_its_reason(self):
        self.push("2026-11-21 09:00:00")
        status, body = self.push("2026-11-21 09:00:00")
        self.assertEqual(status, 200)
        self.assertEqual(body["inserted"], [])
        self.assertIn(DUPLICATE, body["failed"][0]["error"])
        self.assertNotIn("has no attribute", body["failed"][0]["error"])
        self.assertEqual(len(self.checkins_at("2026-11-21 09:00:00")), 1)

    def test_new_record_with_a_duplicate_is_a_partial_success(self):
        self.push("2026-11-21 10:00:00")
        status, body = self.push("2026-11-21 11:00:00", "2026-11-21 10:00:00")
        self.assertEqual(status, 207)
        self.assertEqual(body["inserted"], self.checkins_at("2026-11-21 11:00:00"))
        self.assertEqual(len(body["failed"]), 1)
        self.assertIn(DUPLICATE, body["failed"][0]["error"])

    def test_unexpected_error_is_logged_not_sent(self):
        def logged():
            return frappe.db.count("Error Log", {
                "method": "Offline Checkin Error", "error": ("like", "%x has no attribute y%"),
            })

        before = logged()
        with patch("employee_app.attendance_api.add_log_based_on_employee_field",
                   side_effect=AttributeError("x has no attribute y")):
            status, body = self.push("2026-11-21 12:00:00")
        self.assertEqual(status, 200)
        self.assertEqual(body["failed"][0]["error"], "Could not record this check-in.")
        self.assertEqual(logged(), before + 1)
