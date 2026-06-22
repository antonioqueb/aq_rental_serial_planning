# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

SUBSTITUTION_REASONS = [
    ("damaged", "Dañada"),
    ("lost", "Perdida"),
    ("maintenance", "En mantenimiento"),
    ("unavailable", "No disponible físicamente"),
    ("operational_decision", "Decisión operativa"),
    ("other", "Otro"),
]


class RentalSerialSubstitutionLog(models.Model):
    _name = "rental.serial.substitution.log"
    _description = "Bitácora de sustitución de serie"
    _order = "date desc, id desc"

    reservation_id = fields.Many2one(
        "rental.serial.reservation", string="Reserva", required=True,
        ondelete="cascade", index=True)
    sale_order_id = fields.Many2one(
        "sale.order", string="Pedido", related="reservation_id.sale_order_id",
        store=True, index=True)
    product_id = fields.Many2one("product.product", string="Producto", required=True)
    old_lot_id = fields.Many2one("stock.lot", string="Serie anterior", required=True)
    new_lot_id = fields.Many2one("stock.lot", string="Serie nueva", required=True)
    reason = fields.Selection(SUBSTITUTION_REASONS, string="Motivo", required=True)
    notes = fields.Text(string="Notas")
    user_id = fields.Many2one(
        "res.users", string="Realizado por", default=lambda s: s.env.user, required=True)
    date = fields.Datetime(string="Fecha", default=fields.Datetime.now, required=True)
    old_downtime_id = fields.Many2one(
        "rental.serial.downtime", string="Bloqueo creado para la serie anterior")
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda s: s.env.company, index=True)

    def name_get(self):
        return [(r.id, "%s → %s" % (
            r.old_lot_id.name or "?", r.new_lot_id.name or "?")) for r in self]
