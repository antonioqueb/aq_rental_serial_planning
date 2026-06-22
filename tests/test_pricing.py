# -*- coding: utf-8 -*-
from datetime import datetime, date

from odoo.tests.common import TransactionCase


class TestPricing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({
            "name": "Silla precio", "type": "consu", "list_price": 100.0,
            "rent_ok": True})
        cls.partner = cls.env["res.partner"].create({"name": "Cliente pricing"})
        cls.start = datetime(2026, 9, 5, 10, 0)
        cls.end = datetime(2026, 9, 5, 18, 0)
        wd = str(cls.start.weekday())
        cls.season = cls.env["rental.season"].create({
            "name": "Alta", "date_start": date(2026, 9, 1), "date_end": date(2026, 9, 30)})
        Rule = cls.env["rental.pricing.rule"]
        Rule.create({"name": "Alta +30%", "scope": "global", "apply_on": "rental_price",
                     "pricing_method": "percent_increase", "value": 30.0, "season_id": cls.season.id})
        Rule.create({"name": "Día +15%", "scope": "global", "apply_on": "rental_price",
                     "pricing_method": "percent_increase", "value": 15.0, "weekdays": wd})
        Rule.create({"name": "Entrega", "scope": "global", "apply_on": "delivery_fee",
                     "pricing_method": "amount_surcharge", "value": 300.0})

    def _order(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id, "x_is_event_rental": True,
            "x_billable_start": self.start, "x_billable_end": self.end})
        line = self.env["sale.order.line"].create({
            "order_id": order.id, "product_id": self.product.id, "product_uom_qty": 1.0,
            "x_line_type": "quantity_rental",
            "x_billable_start": self.start, "x_billable_end": self.end})
        return order, line

    def test_season_and_weekday_pricing(self):
        """Case 9: 100 * 1.30 (season) * 1.15 (day) = 149.5 + delivery fee line."""
        order, line = self._order()
        order.action_recompute_rental_pricing()
        self.assertAlmostEqual(line.price_unit, 149.5, places=2)
        fee = order.order_line.filtered(lambda l: l.x_auto_fee == "delivery_fee")
        self.assertEqual(len(fee), 1)
        self.assertAlmostEqual(fee.price_unit, 300.0, places=2)

    def test_price_override_approval(self):
        order, line = self._order()
        line.x_price_override_status = "pending"
        order.action_approve_prices()
        self.assertEqual(line.x_price_override_status, "approved")
        self.assertTrue(line.x_price_override_approved_by)
        self.assertEqual(order.x_price_override_count, 0)
