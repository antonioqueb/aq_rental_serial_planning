# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RentalSerialDowntime(models.Model):
    _name = "rental.serial.downtime"
    _description = "Bloqueo de serie (mantenimiento / daño / perdido)"
    _inherit = ["mail.thread"]
    _order = "start_datetime desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda s: _("Nuevo"))
    lot_id = fields.Many2one(
        "stock.lot", string="Número de serie", required=True, index=True,
        tracking=True)
    product_id = fields.Many2one(
        "product.product", string="Producto",
        related="lot_id.product_id", store=True, index=True)
    reason = fields.Selection(
        [("maintenance", "Mantenimiento"),
         ("cleaning", "Limpieza"),
         ("repair", "Reparación"),
         ("damaged", "Dañado"),
         ("lost", "Perdido"),
         ("internal_use", "Uso interno"),
         ("other", "Otro")],
        string="Motivo", required=True, default="maintenance", tracking=True)
    start_datetime = fields.Datetime(string="Inicio", required=True, index=True)
    end_datetime = fields.Datetime(
        string="Fin", index=True,
        help="Déjalo vacío para un bloqueo abierto (bloquea indefinidamente).")
    state = fields.Selection(
        [("scheduled", "Programado"),
         ("in_progress", "En proceso"),
         ("done", "Terminado"),
         ("cancelled", "Cancelado")],
        string="Estado", default="scheduled", required=True, tracking=True, index=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company, index=True)
    notes = fields.Text(string="Notas")

    _sql_constraints = [
        ("downtime_period_chk",
         "CHECK (end_datetime IS NULL OR end_datetime > start_datetime)",
         "El fin del bloqueo debe ser posterior a su inicio."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.serial.downtime") or _("Nuevo")
        return super().create(vals_list)

    @api.constrains("lot_id", "start_datetime", "end_datetime", "state")
    def _check_overlap_with_reservation(self):
        """Warn (block) if a downtime is scheduled over an active reservation."""
        for rec in self:
            if rec.state not in ("scheduled", "in_progress") or not rec.lot_id:
                continue
            end = rec.end_datetime or fields.Datetime.to_datetime("2099-12-31")
            overlap = self.env["rental.serial.reservation"].search_count([
                ("lot_id", "=", rec.lot_id.id),
                ("state", "in", ("reserved", "prepared", "picked_up",
                                 "delivered", "in_use")),
                ("reservation_block_start", "<", end),
                ("reservation_block_end", ">", rec.start_datetime),
            ])
            if overlap:
                raise ValidationError(_(
                    "La serie '%s' ya tiene una reserva activa en este periodo; "
                    "resuélvela antes de programar el bloqueo.",
                    rec.lot_id.name))

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_done(self):
        self.write({"state": "done",
                    "end_datetime": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancelled"})
