# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["rental.availability.service"]
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create({
            "name": "Sillas Manhattan",
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
        })
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"SILLA-{i:03d}", "product_id": cls.product.id}
            for i in range(1, 21)
        ])
        # Put one physical unit per serial in stock.
        for lot in cls.lots:
            cls.env["stock.quant"].create({
                "product_id": cls.product.id,
                "lot_id": lot.id,
                "location_id": cls.stock_loc.id,
                "quantity": 1.0,
            })
        cls.partner = cls.env["res.partner"].create({"name": "Event Co"})
        cls.start = datetime(2026, 8, 6, 8, 0)   # Thursday
        cls.end = datetime(2026, 8, 11, 18, 0)   # Tuesday

    def test_all_available_initially(self):
        data = self.service.get_product_availability(
            self.product.id, self.start, self.end)
        self.assertEqual(data["total_serials"], 20)
        self.assertEqual(data["available_count"], 20)

    def test_partial_reservation_keeps_rest_available(self):
        """Case 1: reserve 5 serials, 15 remain available in the period."""
        for lot in self.lots[:5]:
            self.env["rental.serial.reservation"].create({
                "product_id": self.product.id,
                "lot_id": lot.id,
                "partner_id": self.partner.id,
                "reservation_block_start": self.start,
                "reservation_block_end": self.end,
                "state": "reserved",
            })
        data = self.service.get_product_availability(
            self.product.id, self.start, self.end)
        self.assertEqual(data["available_count"], 15)
        self.assertEqual(data["reserved_count"], 5)

    def test_downtime_blocks_serial(self):
        """Case 6: a serial in maintenance is not available."""
        self.env["rental.serial.downtime"].create({
            "lot_id": self.lots[9].id,
            "reason": "maintenance",
            "start_datetime": datetime(2026, 8, 3, 0, 0),
            "end_datetime": datetime(2026, 8, 5, 0, 0),
        })
        data = self.service.get_product_availability(
            self.product.id,
            datetime(2026, 8, 4, 0, 0), datetime(2026, 8, 4, 12, 0))
        self.assertNotIn(self.lots[9].id, data["available_serials"])
        self.assertIn(self.lots[9].id, data["unavailable_serials"])

    def test_billable_vs_block_period(self):
        """Case 2: blocking is computed on the operational period, not billable."""
        # Reservation blocks Thu-Tue although billable is Saturday only.
        self.env["rental.serial.reservation"].create({
            "product_id": self.product.id,
            "lot_id": self.lots[0].id,
            "partner_id": self.partner.id,
            "rental_billable_start": datetime(2026, 8, 8, 10, 0),
            "rental_billable_end": datetime(2026, 8, 8, 23, 59),
            "reservation_block_start": self.start,
            "reservation_block_end": self.end,
            "state": "reserved",
        })
        # Querying Thursday (outside billable but inside block) -> unavailable.
        avail = self.service.get_available_serials(
            self.product.id,
            datetime(2026, 8, 6, 9, 0), datetime(2026, 8, 6, 12, 0))
        self.assertNotIn(self.lots[0], avail)
