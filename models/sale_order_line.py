# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .rental_package import LINE_TYPES


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # Package handling
    x_is_package_parent = fields.Boolean(string="Línea padre de paquete")
    x_package_id = fields.Many2one("rental.package.template", string="Paquete")
    x_package_line_id = fields.Many2one("rental.package.template.line",
                                        string="Línea de paquete")
    x_parent_package_line_id = fields.Many2one(
        "sale.order.line", string="Línea de paquete padre", ondelete="cascade")
    x_child_line_ids = fields.One2many(
        "sale.order.line", "x_parent_package_line_id", string="Componentes explotados")

    # Mixed inventory line type (Section 2-3)
    x_line_type = fields.Selection(LINE_TYPES, string="Tipo operativo")
    x_quantity_reservation_ids = fields.One2many(
        "rental.quantity.reservation", "sale_order_line_id", string="Reservas por cantidad")
    x_quantity_reservation_count = fields.Integer(compute="_compute_qty_reservation_count")

    # Shortage / oversell (Section 6)
    x_shortage_allowed = fields.Boolean(string="Shortage permitido")
    x_shortage_qty = fields.Float(string="Faltante")
    x_shortage_status = fields.Selection(
        [("none", "Sin faltante"), ("warning", "Faltante por conseguir"),
         ("pending", "Pendiente de autorización"), ("sourced", "Conseguido"),
         ("blocked", "Bloqueado")],
        string="Estado de shortage", default="none")
    x_shortage_need_ids = fields.One2many(
        "rental.shortage.need", "sale_order_line_id", string="Faltantes")
    x_requires_shortage_approval = fields.Boolean(string="Requiere autorización de shortage")
    x_shortage_approved_by = fields.Many2one("res.users", string="Shortage autorizado por")
    x_shortage_approved_date = fields.Datetime(string="Fecha de autorización de shortage")

    # Advanced pricing / overrides (Section 11)
    x_price_computed = fields.Float(string="Precio calculado")
    x_auto_fee = fields.Char(string="Cargo automático")
    x_price_override = fields.Boolean(string="Precio modificado")
    x_price_override_reason = fields.Char(string="Motivo del override")
    x_price_override_requested_by = fields.Many2one("res.users", string="Solicitado por")
    x_price_override_approved_by = fields.Many2one("res.users", string="Aprobado por")
    x_price_override_approved_date = fields.Datetime(string="Fecha de aprobación")
    x_price_override_status = fields.Selection(
        [("none", "Sin override"), ("pending", "Pendiente"),
         ("approved", "Aprobado"), ("rejected", "Rechazado")],
        string="Estado del override", default="none")

    @api.onchange("price_unit")
    def _onchange_price_override(self):
        """Flag a manual price change that deviates from the computed price."""
        for line in self:
            ref = line.x_price_computed
            if not ref or abs((line.price_unit or 0.0) - ref) <= 0.01:
                continue
            if line.env.user.has_group("aq_rental_serial_planning.group_rental_pricing_manager"):
                line.x_price_override = True
                line.x_price_override_status = "approved"
                line.x_price_override_approved_by = line.env.uid
            else:
                line.x_price_override = True
                line.x_price_override_status = "pending"
                line.x_price_override_requested_by = line.env.uid

    # Serial handling
    x_requires_serial_assignment = fields.Boolean(
        string="Requiere asignación de serie",
        compute="_compute_requires_serial", store=True)
    x_serial_reservation_ids = fields.One2many(
        "rental.serial.reservation", "sale_order_line_id", string="Reservas por serie")
    x_reserved_lot_ids = fields.Many2many(
        "stock.lot", compute="_compute_reserved_lots", string="Series reservadas")
    x_reserved_serial_count = fields.Integer(
        string="Series reservadas", compute="_compute_reserved_lots")

    # Per-line periods (fall back to order-level defaults)
    x_billable_start = fields.Datetime(string="Inicio facturable")
    x_billable_end = fields.Datetime(string="Fin facturable")
    x_block_start = fields.Datetime(string="Inicio de bloqueo")
    x_block_end = fields.Datetime(string="Fin de bloqueo")

    x_available_qty_for_period = fields.Float(
        string="Disponible en el periodo", compute="_compute_available_qty")
    x_conflict_warning = fields.Char(string="Aviso de conflicto",
                                     compute="_compute_conflict_warning")

    def _compute_qty_reservation_count(self):
        data = self.env["rental.quantity.reservation"]._read_group(
            [("sale_order_line_id", "in", self.ids)], ["sale_order_line_id"], ["__count"])
        mapped = {l.id: c for l, c in data if l}
        for line in self:
            line.x_quantity_reservation_count = mapped.get(line.id, 0)

    @api.onchange("product_id")
    def _onchange_x_line_type(self):
        if self.product_id and not self.x_line_type:
            if self.product_id.tracking == "serial":
                self.x_line_type = "serial_rental"
            elif self.product_id.type == "service":
                self.x_line_type = "service"
            else:
                self.x_line_type = "quantity_rental"

    @api.depends("product_id.x_requires_serial_reservation",
                 "product_id.tracking")
    def _compute_requires_serial(self):
        for line in self:
            line.x_requires_serial_assignment = bool(
                line.product_id.x_requires_serial_reservation
                or (line.product_id.tracking == "serial"
                    and line.product_id.x_rental_serial_planning))

    @api.depends("x_serial_reservation_ids.lot_id",
                 "x_serial_reservation_ids.state")
    def _compute_reserved_lots(self):
        for line in self:
            active = line.x_serial_reservation_ids.filtered(
                lambda r: r.state not in ("cancelled", "released"))
            line.x_reserved_lot_ids = active.mapped("lot_id")
            line.x_reserved_serial_count = len(active)

    def _compute_available_qty(self):
        service = self.env["rental.availability.service"]
        for line in self:
            start, end = line._get_block_period()
            if not (line.product_id and start and end
                    and line.product_id.tracking == "serial"):
                line.x_available_qty_for_period = 0.0
                continue
            try:
                data = service.get_product_availability(
                    line.product_id.id, start, end)
                line.x_available_qty_for_period = data["available_count"]
            except ValueError:
                line.x_available_qty_for_period = 0.0

    def _compute_conflict_warning(self):
        for line in self:
            conflicts = line.x_serial_reservation_ids.filtered(
                lambda r: r.conflict_status == "conflict")
            line.x_conflict_warning = (
                _("¡%d conflicto(s) de serie!") % len(conflicts) if conflicts else "")

    # ------------------------------------------------------------------
    # Period derivation
    # ------------------------------------------------------------------
    def _get_billable_period(self):
        self.ensure_one()
        start = self.x_billable_start or self.order_id.x_billable_start
        end = self.x_billable_end or self.order_id.x_billable_end
        # Last resort: native rental fields if present on the line.
        if not start and "start_date" in self._fields:
            start = self.start_date
        if not end and "return_date" in self._fields:
            end = self.return_date
        return start, end

    def _get_block_period(self):
        """Operational block = billable period widened by product buffers.

        Explicit per-line/order block dates win over the derived value.
        """
        self.ensure_one()
        start = self.x_block_start or self.order_id.x_block_start
        end = self.x_block_end or self.order_id.x_block_end
        if start and end:
            return start, end
        b_start, b_end = self._get_billable_period()
        if not (b_start and b_end):
            return start, end
        tmpl = self.product_id.product_tmpl_id
        pre = (tmpl.x_default_preparation_hours
               + tmpl.x_default_delivery_buffer_hours)
        post = (tmpl.x_default_return_buffer_hours
                + tmpl.x_default_cleaning_hours)
        return (b_start - timedelta(hours=pre),
                b_end + timedelta(hours=post))

    # ------------------------------------------------------------------
    # Package explosion (Section 4.2)
    # ------------------------------------------------------------------
    def _explode_package(self):
        self.ensure_one()
        package = self.x_package_id
        if not package:
            raise UserError(_("Esta línea no está vinculada a un paquete."))
        # Remove previously exploded children before re-exploding.
        self.x_child_line_ids.unlink()
        self.x_is_package_parent = True
        b_start, b_end = self._get_billable_period()
        blk_start, blk_end = self._get_block_period()
        hide = package.hide_components_on_quote
        sequence = self.sequence
        for pl in package.line_ids:
            sequence += 1
            lt = pl.line_type or "quantity_rental"
            qty = (pl.quantity or 0.0) * self.product_uom_qty
            vals = {
                "order_id": self.order_id.id,
                "sequence": sequence,
                "x_parent_package_line_id": self.id,
                "x_package_id": package.id,
                "x_package_line_id": pl.id,
                "x_line_type": lt,
                "x_billable_start": b_start,
                "x_billable_end": b_end,
                "x_block_start": blk_start,
                "x_block_end": blk_end,
                "discount": pl.discount_percentage,
            }
            if lt == "note":
                vals.update({"display_type": "line_note",
                             "name": pl.name or (pl.product_id.display_name or _("Nota"))})
                self.create(vals)
                continue
            if lt in ("manual_charge", "manual_discount"):
                price = pl.fixed_price or (pl.product_id.lst_price if pl.product_id else 0.0)
                if lt == "manual_discount":
                    price = -abs(price)
                vals.update({
                    "product_id": pl.product_id.id or False,
                    "name": pl.name or (pl.product_id.display_name if pl.product_id else _("Cargo")),
                    "product_uom_qty": 1.0,
                    "price_unit": price,
                })
                self.create(vals)
                continue
            # serial_rental / quantity_rental / consumable_sale / service
            vals.update({
                "product_id": pl.product_id.id,
                "product_uom_qty": qty,
                "price_unit": 0.0 if hide else (pl.fixed_price or pl.product_id.lst_price),
            })
            if pl.name:
                vals["name"] = pl.name
            child = self.create(vals)
            # quantity rentals auto-create a quantity reservation (no serial needed)
            if lt == "quantity_rental":
                child._ensure_quantity_reservation()
        return True

    # ------------------------------------------------------------------
    # Quantity reservation (Section 5)
    # ------------------------------------------------------------------
    def _ensure_quantity_reservation(self):
        QtyRes = self.env["rental.quantity.reservation"]
        for line in self:
            if line.x_quantity_reservation_ids.filtered(
                    lambda r: r.state not in ("cancelled", "released")):
                continue
            blk_start, blk_end = line._get_block_period()
            if not (blk_start and blk_end):
                continue
            b_start, b_end = line._get_billable_period()
            wh = line.order_id.warehouse_id
            QtyRes.create({
                "sale_order_id": line.order_id.id,
                "sale_order_line_id": line.id,
                "package_id": line.x_package_id.id or False,
                "partner_id": line.order_id.partner_id.id,
                "product_id": line.product_id.id,
                "warehouse_id": wh.id if wh else False,
                "location_id": wh.lot_stock_id.id if wh else False,
                "quantity_reserved": line.product_uom_qty or 1.0,
                "rental_billable_start": b_start,
                "rental_billable_end": b_end,
                "reservation_block_start": blk_start,
                "reservation_block_end": blk_end,
                "state": "reserved",
            })

    def action_reserve_quantity(self):
        for line in self.filtered(lambda l: l.x_line_type == "quantity_rental"):
            line._ensure_quantity_reservation()
        return True

    # ------------------------------------------------------------------
    # Serial assignment (Section 8)
    # ------------------------------------------------------------------
    def _reservation_base_vals(self, lot):
        b_start, b_end = self._get_billable_period()
        blk_start, blk_end = self._get_block_period()
        warehouse = self.order_id.warehouse_id
        return {
            "sale_order_id": self.order_id.id,
            "sale_order_line_id": self.id,
            "partner_id": self.order_id.partner_id.id,
            "product_id": self.product_id.id,
            "lot_id": lot.id,
            "package_id": self.x_package_id.id or False,
            "package_line_id": self.x_package_line_id.id or False,
            "warehouse_id": warehouse.id if warehouse else False,
            "location_id": warehouse.lot_stock_id.id if warehouse else False,
            "rental_billable_start": b_start,
            "rental_billable_end": b_end,
            "reservation_block_start": blk_start,
            "reservation_block_end": blk_end,
            "state": "draft",
        }

    def action_auto_assign_serials(self):
        """Pick the best available serials for the missing quantity."""
        Reservation = self.env["rental.serial.reservation"]
        service = self.env["rental.availability.service"]
        for line in self:
            if not line.x_requires_serial_assignment:
                continue
            blk_start, blk_end = line._get_block_period()
            if not (blk_start and blk_end):
                raise UserError(_(
                    "Define un periodo facturable u operativo para la línea '%s' "
                    "antes de asignar series.", line.product_id.display_name))
            needed = int(line.product_uom_qty) - line.x_reserved_serial_count
            if needed <= 0:
                continue
            warehouse = line.order_id.warehouse_id
            location_id = warehouse.lot_stock_id.id if warehouse else None
            available = service.get_available_serials(
                line.product_id.id, blk_start, blk_end, location_id)
            available = available - line.x_reserved_lot_ids
            available = line._sort_serials(available)
            if len(available) < needed:
                raise UserError(_(
                    "Solo hay %(have)d serie(s) disponible(s) de '%(prod)s' en el "
                    "periodo operativo, pero se requieren %(need)d.",
                    have=len(available), prod=line.product_id.display_name,
                    need=needed))
            # Lock candidate lots, then create reservations one by one so the
            # EXCLUDE constraint serialises concurrent allocation.
            for lot in available[:needed]:
                Reservation.create(line._reservation_base_vals(lot))
        return True

    def action_open_manual_assign(self):
        self.ensure_one()
        blk_start, blk_end = self._get_block_period()
        return {
            "type": "ir.actions.act_window",
            "name": _("Asignar series: %s") % self.product_id.display_name,
            "res_model": "rental.serial.assign.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_sale_order_line_id": self.id,
                "default_product_id": self.product_id.id,
                "default_block_start": blk_start,
                "default_block_end": blk_end,
            },
        }

    def _sort_serials(self, lots):
        """Order: fewest recent moves, then name. Cheap heuristic for wear."""
        move_lines = self.env["stock.move.line"]._read_group(
            [("lot_id", "in", lots.ids)], ["lot_id"], ["__count"])
        move_count = {lot.id: count for lot, count in move_lines if lot}
        return lots.sorted(key=lambda l: (move_count.get(l.id, 0), l.name or ""))

    def action_view_line_reservations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Series de %s") % self.product_id.display_name,
            "res_model": "rental.serial.reservation",
            "view_mode": "list,form",
            "domain": [("sale_order_line_id", "=", self.id)],
            "context": {"default_sale_order_line_id": self.id,
                        "default_product_id": self.product_id.id},
        }
