# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestMixedInventory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.chair = cls._make("Silla serie", "serial", 10)
        cls.linen = cls._make("Mantel", "none", 50)
        cls.partner = cls.env["res.partner"].create({"name": "Evento Mix"})

    @classmethod
    def _make(cls, name, tracking, qty):
        product = cls.env["product.product"].create({
            "name": name, "type": "consu", "is_storable": True,
            "tracking": tracking, "rent_ok": True,
            "x_rental_serial_planning": tracking == "serial",
            "x_rental_package_eligible": True})
        if tracking == "serial":
            lots = cls.env["stock.lot"].create([
                {"name": f"{name[:3]}-{i}", "product_id": product.id} for i in range(qty)])
            for lot in lots:
                cls.env["stock.quant"].create({
                    "product_id": product.id, "lot_id": lot.id,
                    "location_id": cls.stock_loc.id, "quantity": 1.0})
        else:
            cls.env["stock.quant"].create({
                "product_id": product.id, "location_id": cls.stock_loc.id, "quantity": qty})
        return product

    def test_package_line_type_autoclassify(self):
        pkg = self.env["rental.package.template"].create({
            "name": "Mix", "line_ids": [
                (0, 0, {"product_id": self.chair.id, "quantity": 5}),
                (0, 0, {"product_id": self.linen.id, "quantity": 10}),
            ]})
        chair_line = pkg.line_ids.filtered(lambda l: l.product_id == self.chair)
        linen_line = pkg.line_ids.filtered(lambda l: l.product_id == self.linen)
        self.assertEqual(chair_line.line_type, "serial_rental")
        self.assertEqual(linen_line.line_type, "quantity_rental")

    def test_quantity_availability(self):
        s = datetime(2026, 10, 3, 8, 0)
        e = datetime(2026, 10, 7, 18, 0)
        svc = self.env["rental.availability.service"]
        data = svc.get_quantity_availability(self.linen.id, s, e, requested_qty=30)
        self.assertEqual(data["physical_qty"], 50)
        self.assertEqual(data["available_qty"], 50)
        self.assertEqual(data["status"], "available")
        # reserve 40, then only 10 remain -> shortage on a 30 request
        self.env["rental.quantity.reservation"].create({
            "product_id": self.linen.id, "partner_id": self.partner.id,
            "quantity_reserved": 40, "state": "reserved",
            "reservation_block_start": s, "reservation_block_end": e})
        data2 = svc.get_quantity_availability(self.linen.id, s, e, requested_qty=30)
        self.assertEqual(data2["reserved_qty"], 40)
        self.assertEqual(data2["available_qty"], 10)
        self.assertEqual(data2["status"], "available_with_shortage")
        self.assertEqual(data2["shortage_qty"], 20)
