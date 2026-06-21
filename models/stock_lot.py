# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class StockLot(models.Model):
    _inherit = "stock.lot"

    x_reservation_ids = fields.One2many(
        "rental.serial.reservation", "lot_id", string="Reservations")
    x_reservation_count = fields.Integer(compute="_compute_rental_counts")
    x_downtime_ids = fields.One2many(
        "rental.serial.downtime", "lot_id", string="Downtime")
    x_downtime_count = fields.Integer(compute="_compute_rental_counts")
    x_rental_revenue = fields.Monetary(
        string="Rental Revenue", compute="_compute_rental_revenue",
        currency_field="x_currency_id")
    x_currency_id = fields.Many2one(
        "res.currency", compute="_compute_rental_revenue")

    def _compute_rental_counts(self):
        res_data = self.env["rental.serial.reservation"].read_group(
            [("lot_id", "in", self.ids)], ["lot_id"], ["lot_id"])
        res_map = {d["lot_id"][0]: d["__count"] for d in res_data}
        dt_data = self.env["rental.serial.downtime"].read_group(
            [("lot_id", "in", self.ids)], ["lot_id"], ["lot_id"])
        dt_map = {d["lot_id"][0]: d["__count"] for d in dt_data}
        for lot in self:
            lot.x_reservation_count = res_map.get(lot.id, 0)
            lot.x_downtime_count = dt_map.get(lot.id, 0)

    def _compute_rental_revenue(self):
        """Best-effort revenue attribution per serial via its order lines."""
        for lot in self:
            lot.x_currency_id = (lot.company_id or self.env.company).currency_id
            lines = lot.x_reservation_ids.mapped("sale_order_line_id")
            # Split each line's subtotal across the serials reserved on it.
            revenue = 0.0
            for line in lines:
                serials_on_line = len(line.x_serial_reservation_ids) or 1
                revenue += (line.price_subtotal or 0.0) / serials_on_line
            lot.x_rental_revenue = revenue

    def action_view_reservations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reservations: %s") % self.name,
            "res_model": "rental.serial.reservation",
            "view_mode": "list,form,calendar",
            "domain": [("lot_id", "=", self.id)],
            "context": {"default_lot_id": self.id,
                        "default_product_id": self.product_id.id},
        }
