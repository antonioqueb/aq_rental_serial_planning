# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_is_event_rental = fields.Boolean(string="Renta de evento")
    x_event_name = fields.Char(string="Nombre del evento")
    x_event_location = fields.Char(string="Ubicación del evento")
    x_event_start = fields.Datetime(string="Inicio del evento")
    x_event_end = fields.Datetime(string="Fin del evento")

    # Default periods propagated to lines that don't override them.
    x_billable_start = fields.Datetime(string="Inicio facturable")
    x_billable_end = fields.Datetime(string="Fin facturable")
    x_block_start = fields.Datetime(string="Inicio de bloqueo")
    x_block_end = fields.Datetime(string="Fin de bloqueo")
    x_logistics_notes = fields.Text(string="Notas logísticas")

    x_reservation_ids = fields.One2many(
        "rental.serial.reservation", "sale_order_id", string="Reservas por serie")
    x_reservation_count = fields.Integer(string="N° reservas", compute="_compute_reservation_stats")
    x_reservation_conflict_count = fields.Integer(
        string="N° conflictos", compute="_compute_reservation_stats")

    x_serial_picking_count = fields.Integer(
        string="N° transferencias", compute="_compute_reservation_stats")

    @api.depends("x_reservation_ids.conflict_status",
                 "x_reservation_ids.delivery_picking_id",
                 "x_reservation_ids.return_picking_id")
    def _compute_reservation_stats(self):
        for order in self:
            order.x_reservation_count = len(order.x_reservation_ids)
            order.x_reservation_conflict_count = len(
                order.x_reservation_ids.filtered(
                    lambda r: r.conflict_status == "conflict"))
            pickings = (order.x_reservation_ids.mapped("delivery_picking_id")
                        | order.x_reservation_ids.mapped("return_picking_id"))
            order.x_serial_picking_count = len(pickings)

    def _report_reservations(self):
        """Reservations sorted for the logistics roadmap PDF."""
        self.ensure_one()
        return self.x_reservation_ids.filtered(
            lambda r: r.state != "cancelled").sorted(
            key=lambda r: (r.product_id.display_name or "",
                           r.reservation_block_start or fields.Datetime.now(),
                           r.lot_id.name or ""))

    def action_view_serial_pickings(self):
        self.ensure_one()
        pickings = (self.x_reservation_ids.mapped("delivery_picking_id")
                    | self.x_reservation_ids.mapped("return_picking_id"))
        return {
            "type": "ir.actions.act_window",
            "name": _("Transferencias por serie"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", pickings.ids)],
        }

    @api.onchange("x_event_start", "x_event_end")
    def _onchange_event_dates(self):
        """Pre-fill billable period from the event dates as a convenience."""
        if self.x_event_start and not self.x_billable_start:
            self.x_billable_start = self.x_event_start
        if self.x_event_end and not self.x_billable_end:
            self.x_billable_end = self.x_event_end

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_serial_reservations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reservas por serie"),
            "res_model": "rental.serial.reservation",
            "view_mode": "list,form,calendar",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id,
                        "default_partner_id": self.partner_id.id},
        }

    def action_explode_packages(self):
        for order in self:
            for line in order.order_line.filtered(
                    lambda l: l.x_package_id and l.x_is_package_parent):
                line._explode_package()
        return True

    def action_open_planning_board(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "aq_rental_planning_board",
            "name": _("Planeación - %s") % self.name,
            "params": {"sale_order_id": self.id},
        }

    # ------------------------------------------------------------------
    # Confirmation hook: turn reservations into hard blocks.
    # ------------------------------------------------------------------
    def _action_confirm(self):
        res = super()._action_confirm()
        for order in self:
            reservations = order.x_reservation_ids.filtered(
                lambda r: r.state in ("draft", "quotation", "soft_hold"))
            # Re-validate conflicts then lock the serials.
            reservations._check_serial_conflicts()
            reservations.action_reserve()
        return res
