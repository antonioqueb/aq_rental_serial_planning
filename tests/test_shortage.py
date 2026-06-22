# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestShortage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create({
            "name": "Mantel genérico", "type": "consu", "is_storable": True,
            "tracking": "none", "rent_ok": True, "x_rental_package_eligible": True})
        cls.env["stock.quant"].create({
            "product_id": cls.product.id, "location_id": cls.stock_loc.id, "quantity": 80.0})
        cls.partner = cls.env["res.partner"].create({"name": "Evento Shortage"})
        cls.policy = cls.env["rental.shortage.policy"].create({
            "name": "Global 25%", "scope": "global", "allow_shortage": True,
            "shortage_type": "percent", "max_shortage_percent": 25.0,
            "requires_manager_approval": False, "default_resolution": "manual_task"})
        cls.start = datetime(2026, 11, 7, 8, 0)
        cls.end = datetime(2026, 11, 11, 18, 0)

    def _order_with_qty(self, qty):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        line = self.env["sale.order.line"].create({
            "order_id": order.id, "product_id": self.product.id,
            "product_uom_qty": qty, "x_line_type": "quantity_rental",
            "x_block_start": self.start, "x_block_end": self.end})
        self.env["rental.quantity.reservation"].create({
            "sale_order_id": order.id, "sale_order_line_id": line.id,
            "partner_id": self.partner.id, "product_id": self.product.id,
            "quantity_reserved": qty, "state": "reserved",
            "reservation_block_start": self.start, "reservation_block_end": self.end})
        return order, line

    def test_shortage_allowed_within_limit(self):
        """Case 2: request 100 with 80 stock, policy allows 25% -> need created."""
        order, line = self._order_with_qty(100)
        order._process_quantity_shortage()
        self.assertEqual(line.x_shortage_status, "warning")
        self.assertEqual(round(line.x_shortage_qty), 20)
        needs = self.env["rental.shortage.need"].search([("sale_order_id", "=", order.id)])
        self.assertEqual(len(needs), 1)
        self.assertEqual(round(needs.shortage_qty), 20)

    def test_shortage_exceeds_limit_blocks(self):
        """Case 3: request 120 -> shortage 40 > 25% (30) -> confirmation blocked."""
        order, line = self._order_with_qty(120)
        with self.assertRaises(UserError):
            order._process_quantity_shortage()

    def test_policy_resolution(self):
        found = self.env["rental.shortage.policy"]._find_policy(self.product)
        self.assertEqual(found, self.policy)
        ev = found.evaluate(100, 80)
        self.assertTrue(ev["allowed"])
        self.assertEqual(ev["status"], "available_with_shortage")
        self.assertEqual(round(ev["shortage_qty"]), 20)
