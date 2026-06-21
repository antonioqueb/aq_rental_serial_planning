# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # Package handling
    x_is_package_parent = fields.Boolean(string="Package Parent")
    x_package_id = fields.Many2one("rental.package.template", string="Package")
    x_package_line_id = fields.Many2one("rental.package.template.line")
    x_parent_package_line_id = fields.Many2one(
        "sale.order.line", string="Parent Package Line", ondelete="cascade")
    x_child_line_ids = fields.One2many(
        "sale.order.line", "x_parent_package_line_id", string="Exploded Components")

    # Serial handling
    x_requires_serial_assignment = fields.Boolean(
        compute="_compute_requires_serial", store=True)
    x_serial_reservation_ids = fields.One2many(
        "rental.serial.reservation", "sale_order_line_id", string="Serial Reservations")
    x_reserved_lot_ids = fields.Many2many(
        "stock.lot", compute="_compute_reserved_lots", string="Reserved Serials")
    x_reserved_serial_count = fields.Integer(compute="_compute_reserved_lots")

    # Per-line periods (fall back to order-level defaults)
    x_billable_start = fields.Datetime(string="Billable Start")
    x_billable_end = fields.Datetime(string="Billable End")
    x_block_start = fields.Datetime(string="Block Start")
    x_block_end = fields.Datetime(string="Block End")

    x_available_qty_for_period = fields.Float(
        string="Available in Period", compute="_compute_available_qty")
    x_conflict_warning = fields.Char(compute="_compute_conflict_warning")

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
                _("%d serial conflict(s)!") % len(conflicts) if conflicts else "")

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
            raise UserError(_("This line is not linked to a package."))
        # Remove previously exploded children before re-exploding.
        self.x_child_line_ids.unlink()
        self.x_is_package_parent = True
        b_start, b_end = self._get_billable_period()
        blk_start, blk_end = self._get_block_period()
        sequence = self.sequence
        for pl in package.line_ids:
            sequence += 1
            child = self.create({
                "order_id": self.order_id.id,
                "product_id": pl.product_id.id,
                "product_uom_qty": pl.quantity * self.product_uom_qty,
                "sequence": sequence,
                "x_parent_package_line_id": self.id,
                "x_package_id": package.id,
                "x_package_line_id": pl.id,
                "x_billable_start": b_start,
                "x_billable_end": b_end,
                "x_block_start": blk_start,
                "x_block_end": blk_end,
                # Components priced inside the parent when hidden.
                "price_unit": 0.0 if package.hide_components_on_quote else pl.product_id.lst_price,
                "discount": pl.discount_percentage,
            })
            if package.hide_components_on_quote:
                child.product_uom_qty = pl.quantity * self.product_uom_qty
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
                    "Define a billable or operational period for line '%s' "
                    "before assigning serials.", line.product_id.display_name))
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
                    "Only %(have)d serial(s) available for '%(prod)s' in the "
                    "operational period, but %(need)d are required.",
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
            "name": _("Assign Serials: %s") % self.product_id.display_name,
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
        move_lines = self.env["stock.move.line"].read_group(
            [("lot_id", "in", lots.ids)], ["lot_id"], ["lot_id"])
        move_count = {m["lot_id"][0]: m["__count"]
                      for m in move_lines if m.get("lot_id")}
        return lots.sorted(key=lambda l: (move_count.get(l.id, 0), l.name or ""))

    def action_view_line_reservations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Serials for %s") % self.product_id.display_name,
            "res_model": "rental.serial.reservation",
            "view_mode": "list,form",
            "domain": [("sale_order_line_id", "=", self.id)],
            "context": {"default_sale_order_line_id": self.id,
                        "default_product_id": self.product_id.id},
        }
