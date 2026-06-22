# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rental_serial_reservation import STATE_SELECTION
from .rental_availability_service import BLOCKING_STATES


class RentalQuantityReservation(models.Model):
    _name = "rental.quantity.reservation"
    _description = "Reserva de renta por cantidad"
    _inherit = ["mail.thread"]
    _order = "reservation_block_start desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        index=True, default=lambda s: _("Nuevo"))
    state = fields.Selection(
        STATE_SELECTION, string="Estado", default="draft", required=True,
        tracking=True, index=True)

    sale_order_id = fields.Many2one("sale.order", string="Pedido", index=True, ondelete="cascade")
    sale_order_line_id = fields.Many2one("sale.order.line", string="Línea", index=True, ondelete="cascade")
    package_id = fields.Many2one("rental.package.template", string="Paquete")
    partner_id = fields.Many2one("res.partner", string="Cliente", tracking=True)
    product_id = fields.Many2one("product.product", string="Producto", required=True, index=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén")
    location_id = fields.Many2one("stock.location", string="Ubicación origen")
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, index=True,
        default=lambda s: s.env.company)

    quantity_reserved = fields.Float(string="Cantidad reservada", default=1.0, required=True)
    quantity_delivered = fields.Float(string="Cantidad entregada")
    quantity_returned = fields.Float(string="Cantidad devuelta")
    quantity_lost = fields.Float(string="Cantidad perdida")
    quantity_damaged = fields.Float(string="Cantidad dañada")
    shortage_qty = fields.Float(string="Faltante", help="Unidades por conseguir (sobreventa).")

    rental_billable_start = fields.Datetime(string="Inicio facturable")
    rental_billable_end = fields.Datetime(string="Fin facturable")
    reservation_block_start = fields.Datetime(string="Inicio de bloqueo", required=True, index=True)
    reservation_block_end = fields.Datetime(string="Fin de bloqueo", required=True, index=True)
    auto_release_policy = fields.Selection(
        [("on_block_end", "Automática al fin del bloqueo"),
         ("on_return_validation", "Al validar la devolución"),
         ("manual_only", "Solo manual")],
        string="Política de liberación", default="on_return_validation", required=True)
    notes = fields.Text(string="Notas")

    _sql_constraints = [
        ("qty_block_chk", "CHECK (reservation_block_end > reservation_block_start)",
         "El fin del bloqueo debe ser posterior al inicio."),
        ("qty_positive_chk", "CHECK (quantity_reserved > 0)",
         "La cantidad reservada debe ser positiva."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.quantity.reservation") or _("Nuevo")
        records = super().create(vals_list)
        records._compute_shortage()
        return records

    def _compute_shortage(self):
        """Best-effort: how much of this reservation exceeds free availability."""
        service = self.env["rental.availability.service"]
        for rec in self:
            if rec.state not in BLOCKING_STATES or not rec.product_id:
                continue
            data = service.get_quantity_availability(
                rec.product_id.id, rec.reservation_block_start,
                rec.reservation_block_end, rec.location_id.id or None,
                ignore_reservation_ids=rec.ids)
            free = data["available_qty"]
            rec.shortage_qty = max(0.0, rec.quantity_reserved - free)

    # ------------------------------------------------------------------
    # state machine (mirrors the serial reservation semantics)
    # ------------------------------------------------------------------
    def action_reserve(self):
        self.write({"state": "reserved"})
        self._compute_shortage()

    def action_prepare(self):
        self.write({"state": "prepared"})

    def action_pickup(self):
        self.write({"state": "picked_up"})

    def action_deliver(self):
        for rec in self:
            rec.quantity_delivered = rec.quantity_delivered or rec.quantity_reserved
        self.write({"state": "delivered"})

    def action_set_in_use(self):
        self.write({"state": "in_use"})

    def action_return(self):
        for rec in self:
            if not rec.quantity_returned:
                rec.quantity_returned = max(
                    rec.quantity_delivered - rec.quantity_lost - rec.quantity_damaged, 0.0)
        self.write({"state": "returned"})

    def action_release(self):
        self.write({"state": "released"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    # ------------------------------------------------------------------
    @api.model
    def _cron_release_expired(self):
        now = fields.Datetime.now()
        to_release = self.search([
            ("auto_release_policy", "=", "on_block_end"),
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_end", "<", now)])
        to_release.write({"state": "released"})
