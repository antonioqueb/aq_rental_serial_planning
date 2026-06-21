# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RentalSerialAssignWizard(models.TransientModel):
    _name = "rental.serial.assign.wizard"
    _description = "Asistente de asignación manual de series"

    sale_order_line_id = fields.Many2one("sale.order.line", string="Línea de pedido", required=True)
    product_id = fields.Many2one("product.product", string="Producto", required=True, readonly=True)
    block_start = fields.Datetime(string="Inicio de bloqueo", required=True)
    block_end = fields.Datetime(string="Fin de bloqueo", required=True)
    location_id = fields.Many2one("stock.location", string="Ubicación")
    required_qty = fields.Integer(string="Cantidad requerida", compute="_compute_required_qty")
    line_ids = fields.One2many(
        "rental.serial.assign.wizard.line", "wizard_id", string="Series")

    @api.depends("sale_order_line_id")
    def _compute_required_qty(self):
        for wiz in self:
            sol = wiz.sale_order_line_id
            wiz.required_qty = int(sol.product_uom_qty - sol.x_reserved_serial_count) if sol else 0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        sol = self.env["sale.order.line"].browse(res.get("sale_order_line_id"))
        if sol and res.get("block_start") and res.get("block_end"):
            res["line_ids"] = self._build_candidate_lines(
                sol.product_id, res["block_start"], res["block_end"],
                res.get("location_id"), sol)
        return res

    def _build_candidate_lines(self, product, start, end, location_id, sol):
        service = self.env["rental.availability.service"]
        already = sol.x_reserved_lot_ids
        all_lots = self.env["stock.lot"].search([("product_id", "=", product.id)])
        available = service.get_available_serials(product.id, start, end, location_id)
        unavail = service.get_unavailable_serials(product.id, start, end, location_id)
        lines = []
        for lot in all_lots:
            if lot in already:
                status = "in_reservation"
            elif lot in available:
                status = "available"
            elif lot in unavail:
                status = "blocked"
            else:
                status = "no_stock"
            lines.append((0, 0, {
                "lot_id": lot.id,
                "status": status,
                "selected": False,
            }))
        return lines

    def action_assign(self):
        self.ensure_one()
        chosen = self.line_ids.filtered("selected")
        if not chosen:
            raise UserError(_("Selecciona al menos una serie."))
        invalid = chosen.filtered(lambda l: l.status not in ("available",))
        if invalid:
            raise UserError(_(
                "Estas series no están disponibles: %s",
                ", ".join(invalid.mapped("lot_id.name"))))
        Reservation = self.env["rental.serial.reservation"]
        sol = self.sale_order_line_id
        for wline in chosen:
            Reservation.create(sol._reservation_base_vals(wline.lot_id))
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": sol.order_id.id,
            "view_mode": "form",
            "target": "current",
        }


class RentalSerialAssignWizardLine(models.TransientModel):
    _name = "rental.serial.assign.wizard.line"
    _description = "Línea del asistente de asignación de series"
    _order = "status, lot_id"

    wizard_id = fields.Many2one("rental.serial.assign.wizard", required=True, ondelete="cascade")
    lot_id = fields.Many2one("stock.lot", string="Número de serie", required=True, readonly=True)
    status = fields.Selection(
        [("available", "Disponible"),
         ("blocked", "Reservado / En uso / Mantenimiento"),
         ("in_reservation", "Ya en esta reserva"),
         ("no_stock", "Sin stock / otra ubicación")],
        string="Estado", readonly=True)
    selected = fields.Boolean(string="Seleccionar")
