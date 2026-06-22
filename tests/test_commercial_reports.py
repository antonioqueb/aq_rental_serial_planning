# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestCommercialReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create({
            "name": "Bocina report", "type": "consu", "is_storable": True,
            "tracking": "serial", "rent_ok": True, "x_rental_serial_planning": True,
            "list_price": 200.0})
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"BR-{i}", "product_id": cls.product.id} for i in range(3)])
        for lot in cls.lots:
            cls.env["stock.quant"].create({
                "product_id": cls.product.id, "lot_id": lot.id,
                "location_id": cls.stock_loc.id, "quantity": 1.0})
        cls.partner = cls.env["res.partner"].create({"name": "Cliente report"})

    def test_reports_structure(self):
        data = self.env["rental.serial.reservation"].commercial_reports(days=90)
        for key in ("classification", "revenue_by_serial", "damage_by_serial",
                    "margin_by_event", "category_utilization", "package_profit",
                    "projected"):
            self.assertIn(key, data)
        self.assertTrue(any(c["product"] == "Bocina report" for c in data["classification"]))

    def test_saturation_and_damage_classification(self):
        import datetime as dt
        now = dt.datetime.now()
        # block all 3 serials right now -> 100% utilization -> saturated
        for lot in self.lots:
            self.env["rental.serial.reservation"].create({
                "product_id": self.product.id, "lot_id": lot.id,
                "partner_id": self.partner.id, "state": "in_use",
                "reservation_block_start": now - dt.timedelta(days=1),
                "reservation_block_end": now + dt.timedelta(days=2)})
        # a damage on one serial
        self.env["rental.serial.downtime"].create({
            "lot_id": self.lots[0].id, "reason": "damaged", "state": "in_progress",
            "start_datetime": now})
        data = self.env["rental.serial.reservation"].commercial_reports(days=90)
        row = next(c for c in data["classification"] if c["product"] == "Bocina report")
        self.assertEqual(row["status"], "saturated")
        self.assertTrue(row["suggested_purchase"] >= 1)
        self.assertTrue(any(d["lot"] == "BR-0" for d in data["damage_by_serial"]))
