# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    x_serial_reservation_count = fields.Integer(
        string="Reservas por serie activas",
        compute="_compute_serial_reservation_count")

    def _compute_serial_reservation_count(self):
        data = self.env["rental.serial.reservation"]._read_group(
            [("product_id", "in", self.ids),
             ("state", "not in", ("cancelled", "released"))],
            ["product_id"], ["__count"])
        mapped = {product.id: count for product, count in data}
        for product in self:
            product.x_serial_reservation_count = mapped.get(product.id, 0)

    def action_open_serial_availability(self):
        """Smart-button: open the planning board pre-filtered to this product."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "aq_rental_planning_board",
            "name": _("Disponibilidad: %s") % self.display_name,
            "params": {"product_id": self.id},
        }
