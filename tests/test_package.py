# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestPackageAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["rental.availability.service"]
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")

        cls.chair = cls._make_serial_product("Sillas Manhattan", 20)
        cls.table = cls._make_serial_product("Mesa Banquete", 3)

        cls.package = cls.env["rental.package.template"].create({
            "name": "Paquete Evento A",
            "line_ids": [
                (0, 0, {"product_id": cls.chair.id, "quantity": 5, "required": True}),
                (0, 0, {"product_id": cls.table.id, "quantity": 1, "required": True}),
            ],
        })
        cls.start = datetime(2026, 8, 6, 8, 0)
        cls.end = datetime(2026, 8, 11, 18, 0)

    @classmethod
    def _make_serial_product(cls, name, qty):
        product = cls.env["product.product"].create({
            "name": name,
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
            "x_rental_package_eligible": True,
        })
        lots = cls.env["stock.lot"].create([
            {"name": f"{name[:5].upper()}-{i:03d}", "product_id": product.id}
            for i in range(1, qty + 1)
        ])
        for lot in lots:
            cls.env["stock.quant"].create({
                "product_id": product.id,
                "lot_id": lot.id,
                "location_id": cls.stock_loc.id,
                "quantity": 1.0,
            })
        return product

    def test_package_limited_by_scarcest_component(self):
        """Case 3: min(20/5, 3/1) = 3 packages; tables are the limiter."""
        data = self.service.get_package_availability(
            self.package.id, self.start, self.end)
        self.assertEqual(data["max_packages"], 3)
        limiting = [l for l in data["lines"] if l["is_limiting"]]
        limiting_products = {l["product_id"] for l in limiting}
        self.assertIn(self.table.id, limiting_products)
        self.assertNotIn(self.chair.id, limiting_products)
