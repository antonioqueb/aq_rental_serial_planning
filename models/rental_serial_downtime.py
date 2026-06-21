# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RentalSerialDowntime(models.Model):
    _name = "rental.serial.downtime"
    _description = "Rental Serial Downtime (maintenance / damage / lost)"
    _inherit = ["mail.thread"]
    _order = "start_datetime desc"

    name = fields.Char(
        required=True, copy=False, readonly=True, default=lambda s: _("New"))
    lot_id = fields.Many2one(
        "stock.lot", string="Serial Number", required=True, index=True,
        tracking=True)
    product_id = fields.Many2one(
        "product.product", related="lot_id.product_id", store=True, index=True)
    reason = fields.Selection(
        [("maintenance", "Maintenance"),
         ("cleaning", "Cleaning"),
         ("repair", "Repair"),
         ("damaged", "Damaged"),
         ("lost", "Lost"),
         ("internal_use", "Internal Use"),
         ("other", "Other")],
        required=True, default="maintenance", tracking=True)
    start_datetime = fields.Datetime(required=True, index=True)
    end_datetime = fields.Datetime(
        index=True, help="Leave empty for open-ended downtime (blocks indefinitely).")
    state = fields.Selection(
        [("scheduled", "Scheduled"),
         ("in_progress", "In Progress"),
         ("done", "Done"),
         ("cancelled", "Cancelled")],
        default="scheduled", required=True, tracking=True, index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True)
    notes = fields.Text()

    _sql_constraints = [
        ("downtime_period_chk",
         "CHECK (end_datetime IS NULL OR end_datetime > start_datetime)",
         "Downtime end must be after its start."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.serial.downtime") or _("New")
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
                    "Serial '%s' already has an active reservation in this "
                    "period; resolve it before scheduling downtime.",
                    rec.lot_id.name))

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_done(self):
        self.write({"state": "done",
                    "end_datetime": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancelled"})
