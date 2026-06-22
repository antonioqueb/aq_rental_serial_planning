# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .rental_availability_service import BLOCKING_STATES


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_is_event_rental = fields.Boolean(string="Renta de evento")
    x_event_type_id = fields.Many2one("rental.event.type", string="Tipo de evento")
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
        for order in self:
            if order.order_line.filtered(lambda l: l.x_price_override_status == "pending"):
                raise UserError(_(
                    "Hay overrides de precio pendientes de autorización en %s.",
                    order.name))
        res = super()._action_confirm()
        for order in self:
            reservations = order.x_reservation_ids.filtered(
                lambda r: r.state in ("draft", "quotation", "soft_hold"))
            # Re-validate conflicts then lock the serials.
            reservations._check_serial_conflicts()
            reservations.action_reserve()
            order._process_quantity_shortage()
        return res

    # ------------------------------------------------------------------
    # Shortage / oversell processing (Section 6)
    # ------------------------------------------------------------------
    def _process_quantity_shortage(self):
        self.ensure_one()
        Policy = self.env["rental.shortage.policy"]
        Need = self.env["rental.shortage.need"]
        service = self.env["rental.availability.service"]
        is_manager = self.env.user.has_group(
            "aq_rental_serial_planning.group_rental_planner_manager")
        reservations = self.env["rental.quantity.reservation"].search([
            ("sale_order_id", "=", self.id),
            ("state", "in", list(BLOCKING_STATES))])
        for r in reservations:
            avail = service.get_quantity_availability(
                r.product_id.id, r.reservation_block_start, r.reservation_block_end,
                r.location_id.id or None, ignore_reservation_ids=r.ids)
            shortage = max(0.0, r.quantity_reserved - avail["available_qty"])
            line = r.sale_order_line_id
            r.shortage_qty = shortage
            if shortage <= 0:
                if line:
                    line.write({"x_shortage_status": "none", "x_shortage_qty": 0.0})
                continue
            policy = Policy._find_policy(r.product_id, r.package_id)
            ev = policy.evaluate(r.quantity_reserved, avail["available_qty"])
            if ev["status"] == "not_available":
                raise UserError(_(
                    "No hay disponibilidad suficiente de '%(prod)s': faltan "
                    "%(q)d unidades y la política no permite cubrir ese faltante.",
                    prod=r.product_id.display_name, q=int(shortage)))
            approved = bool(line and line.x_shortage_approved_by)
            if ev["requires_approval"] and not approved and not is_manager:
                if line:
                    line.write({
                        "x_shortage_status": "pending", "x_shortage_qty": shortage,
                        "x_requires_shortage_approval": True})
                self._create_shortage_need(r, policy, avail, shortage, state="pending")
                raise UserError(_(
                    "El faltante de '%(prod)s' (%(q)d uds) requiere autorización de "
                    "un gerente antes de confirmar.",
                    prod=r.product_id.display_name, q=int(shortage)))
            # allowed (or a manager is confirming)
            need = self._create_shortage_need(r, policy, avail, shortage, state="approved")
            need._auto_resolve()
            if line:
                line.write({
                    "x_shortage_allowed": True, "x_shortage_qty": shortage,
                    "x_shortage_status": "warning"})

    def _create_shortage_need(self, reservation, policy, avail, shortage, state="draft"):
        Need = self.env["rental.shortage.need"]
        existing = Need.search([
            ("quantity_reservation_id", "=", reservation.id),
            ("state", "not in", ("cancelled", "sourced"))], limit=1)
        vals = {
            "state": state,
            "sale_order_id": self.id,
            "sale_order_line_id": reservation.sale_order_line_id.id or False,
            "quantity_reservation_id": reservation.id,
            "product_id": reservation.product_id.id,
            "package_id": reservation.package_id.id or False,
            "partner_id": self.partner_id.id,
            "event_date": self.x_event_start.date() if self.x_event_start else False,
            "reservation_block_start": reservation.reservation_block_start,
            "reservation_block_end": reservation.reservation_block_end,
            "requested_qty": reservation.quantity_reserved,
            "available_qty": avail["available_qty"],
            "shortage_qty": shortage,
            "policy_id": policy.id or False,
            "resolution_type": policy.default_resolution if policy else "manual_task",
            "vendor_id": policy.vendor_id.id if policy else False,
        }
        if existing:
            existing.write(vals)
            return existing
        return Need.create(vals)

    def action_approve_shortage(self):
        """Manager approves all pending shortages, then confirmation can proceed."""
        for order in self:
            lines = order.order_line.filtered(lambda l: l.x_shortage_status == "pending")
            lines.write({
                "x_shortage_approved_by": self.env.uid,
                "x_shortage_approved_date": fields.Datetime.now(),
                "x_shortage_status": "warning"})
            order.x_shortage_need_ids.filtered(
                lambda n: n.state == "pending").write({"state": "approved"})
        return True

    x_shortage_need_ids = fields.One2many(
        "rental.shortage.need", "sale_order_id", string="Faltantes")
    x_shortage_count = fields.Integer(compute="_compute_shortage_count")

    def _compute_shortage_count(self):
        data = self.env["rental.shortage.need"]._read_group(
            [("sale_order_id", "in", self.ids),
             ("state", "not in", ("cancelled", "sourced"))],
            ["sale_order_id"], ["__count"])
        mapped = {o.id: c for o, c in data if o}
        for order in self:
            order.x_shortage_count = mapped.get(order.id, 0)

    def action_view_shortage_needs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Faltantes por conseguir"),
            "res_model": "rental.shortage.need", "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id},
        }

    # ------------------------------------------------------------------
    # Advanced pricing (Section 11)
    # ------------------------------------------------------------------
    x_price_override_count = fields.Integer(
        compute="_compute_price_override_count", store=True)

    @api.depends("order_line.x_price_override_status")
    def _compute_price_override_count(self):
        for order in self:
            order.x_price_override_count = len(order.order_line.filtered(
                lambda l: l.x_price_override_status == "pending"))

    def action_recompute_rental_pricing(self):
        service = self.env["rental.pricing.service"]
        for order in self:
            for line in order.order_line.filtered(
                    lambda l: l.x_line_type in ("serial_rental", "quantity_rental")
                    and not l.display_type):
                bd = service.compute_line_price(line)
                line.x_price_computed = bd["unit"]
                if line.x_price_override_status in ("pending", "approved"):
                    continue
                line.price_unit = bd["unit"]
            order._apply_order_fee("delivery_fee", _("Cargo de entrega"))
            order._apply_order_fee("cleaning_fee", _("Cargo de limpieza"))
        return True

    def _apply_order_fee(self, apply_on, label):
        self.ensure_one()
        when = self.x_billable_start or fields.Datetime.now()
        rules = self.env["rental.pricing.rule"]._matching(
            apply_on, self.env["product.product"], False,
            self.partner_id, self.x_event_type_id, when, 0.0, 1.0)
        amount = 0.0
        for r in rules:
            amount = r._apply_to(amount)
        existing = self.order_line.filtered(lambda l: l.x_auto_fee == apply_on)
        if amount:
            vals = {"x_auto_fee": apply_on, "x_line_type": "manual_charge",
                    "name": label, "product_uom_qty": 1.0, "price_unit": amount}
            if existing:
                existing[0].write(vals)
                existing[1:].unlink()
            else:
                self.env["sale.order.line"].create(dict(vals, order_id=self.id))
        elif existing:
            existing.unlink()

    def action_approve_prices(self):
        for order in self:
            order.order_line.filtered(
                lambda l: l.x_price_override_status == "pending").write({
                    "x_price_override_status": "approved",
                    "x_price_override_approved_by": self.env.uid,
                    "x_price_override_approved_date": fields.Datetime.now()})
        return True

    # ------------------------------------------------------------------
    # Documents & damage reports (Section 10)
    # ------------------------------------------------------------------
    x_document_ids = fields.One2many(
        "rental.document.instance", "sale_order_id", string="Documentos")
    x_document_count = fields.Integer(compute="_compute_doc_damage_count")
    x_damage_report_ids = fields.One2many(
        "rental.damage.report", "sale_order_id", string="Actas de daño")
    x_damage_count = fields.Integer(compute="_compute_doc_damage_count")

    def _compute_doc_damage_count(self):
        for order in self:
            order.x_document_count = len(order.x_document_ids)
            order.x_damage_count = len(order.x_damage_report_ids)

    def _create_document(self, doc_type):
        self.ensure_one()
        doc = self.env["rental.document.instance"].create({
            "document_type": doc_type,
            "sale_order_id": self.id,
            "partner_id": self.partner_id.id,
        })
        return {
            "type": "ir.actions.act_window", "res_model": "rental.document.instance",
            "res_id": doc.id, "view_mode": "form", "target": "current",
        }

    def action_doc_contract(self):
        return self._create_document("rental_contract")

    def action_doc_liability(self):
        return self._create_document("liability_letter")

    def action_doc_outgoing(self):
        return self._create_document("outgoing_checklist")

    def action_doc_return(self):
        return self._create_document("return_checklist")

    def action_doc_mounting(self):
        return self._create_document("mounting_sheet")

    def action_view_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Documentos"),
            "res_model": "rental.document.instance", "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id, "default_partner_id": self.partner_id.id},
        }

    def action_view_damage_reports(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Actas de daño"),
            "res_model": "rental.damage.report", "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id},
        }

    def action_generate_late_fees(self):
        service = self.env["rental.pricing.service"]
        Line = self.env["sale.order.line"]
        for order in self:
            for r in order.x_reservation_ids.filtered(lambda x: x.is_overdue):
                tag = "late_fee_%s" % r.id
                if order.order_line.filtered(lambda l: l.x_auto_fee == tag):
                    continue
                fee = service.compute_late_return_fee(r)
                if fee > 0:
                    Line.create({
                        "order_id": order.id, "x_line_type": "manual_charge",
                        "x_auto_fee": tag, "product_uom_qty": 1.0, "price_unit": fee,
                        "name": _("Cargo por retraso: %s") % (r.lot_id.name or r.name)})
        return True
