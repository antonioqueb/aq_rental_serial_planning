# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .rental_availability_service import BLOCKING_STATES

STATE_SELECTION = [
    ("draft", "Draft"),
    ("quotation", "Quotation"),
    ("soft_hold", "Soft Hold"),
    ("reserved", "Reserved"),
    ("prepared", "Prepared"),
    ("picked_up", "Picked Up"),
    ("delivered", "Delivered"),
    ("in_use", "In Use"),
    ("returned", "Returned"),
    ("released", "Released"),
    ("cancelled", "Cancelled"),
]

# Forward flow used by the action buttons.
_FORWARD = ["reserved", "prepared", "picked_up", "delivered",
            "in_use", "returned", "released"]


class RentalSerialReservation(models.Model):
    _name = "rental.serial.reservation"
    _description = "Rental Serial Reservation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "reservation_block_start desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True,
        index=True, default=lambda self: _("New"))
    state = fields.Selection(
        STATE_SELECTION, default="draft", required=True, tracking=True, index=True)

    # Commercial links
    sale_order_id = fields.Many2one(
        "sale.order", string="Sale Order", index=True, ondelete="cascade")
    sale_order_line_id = fields.Many2one(
        "sale.order.line", string="Order Line", index=True, ondelete="cascade")
    package_id = fields.Many2one("rental.package.template", string="Package")
    package_line_id = fields.Many2one("rental.package.template.line", string="Package Line")
    partner_id = fields.Many2one("res.partner", string="Customer", tracking=True)

    # Inventory links
    product_id = fields.Many2one(
        "product.product", string="Product", required=True, index=True,
        domain="[('tracking', '=', 'serial')]")
    lot_id = fields.Many2one(
        "stock.lot", string="Serial Number", index=True,
        domain="[('product_id', '=', product_id)]", tracking=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse")
    location_id = fields.Many2one("stock.location", string="Source Location")
    company_id = fields.Many2one(
        "res.company", string="Company", required=True, index=True,
        default=lambda self: self.env.company)
    quantity = fields.Float(string="Quantity", default=1.0)

    # Billable period (what the customer pays)
    rental_billable_start = fields.Datetime(string="Billable Start", tracking=True)
    rental_billable_end = fields.Datetime(string="Billable End", tracking=True)

    # Operational block period (what really blocks inventory)
    reservation_block_start = fields.Datetime(
        string="Block Start", required=True, index=True, tracking=True)
    reservation_block_end = fields.Datetime(
        string="Block End", required=True, index=True, tracking=True)

    # Real-world stamps
    actual_pickup_datetime = fields.Datetime(string="Actual Pickup")
    actual_delivery_datetime = fields.Datetime(string="Actual Delivery")
    actual_return_datetime = fields.Datetime(string="Actual Return")
    actual_release_datetime = fields.Datetime(string="Actual Release")

    auto_release_policy = fields.Selection(
        [("on_block_end", "Auto on block end"),
         ("on_return_validation", "On return validation"),
         ("manual_only", "Manual only")],
        string="Auto-Release Policy", default="on_return_validation", required=True)

    # Soft hold
    soft_hold_until = fields.Datetime(string="Soft Hold Until")
    soft_hold_owner_id = fields.Many2one("res.users", string="Hold Owner")
    soft_hold_reason = fields.Char(string="Hold Reason")

    conflict_status = fields.Selection(
        [("ok", "OK"), ("conflict", "Conflict")],
        string="Conflict", compute="_compute_conflict_status", store=True)
    availability_status = fields.Selection(
        [("available", "Available"), ("blocked", "Blocked")],
        string="Availability", default="available")
    is_overdue = fields.Boolean(
        string="Overdue", compute="_compute_is_overdue", store=False)
    notes = fields.Text(string="Notes")

    # Inventory integration (Section 12)
    delivery_picking_id = fields.Many2one(
        "stock.picking", string="Delivery Transfer", copy=False, readonly=True)
    return_picking_id = fields.Many2one(
        "stock.picking", string="Return Transfer", copy=False, readonly=True)

    _sql_constraints = [
        ("block_period_chk",
         "CHECK (reservation_block_end > reservation_block_start)",
         "The operational block end must be after the block start."),
    ]

    # ------------------------------------------------------------------
    # Defaults / create
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.serial.reservation") or _("New")
        records = super().create(vals_list)
        records._check_serial_conflicts()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Re-check only when something relevant changed.
        if {"lot_id", "reservation_block_start", "reservation_block_end",
                "state"} & set(vals):
            self._check_serial_conflicts()
        return res

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("lot_id", "reservation_block_start", "reservation_block_end", "state")
    def _compute_conflict_status(self):
        for rec in self:
            rec.conflict_status = "conflict" if rec._find_conflicts() else "ok"

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(
                rec.state in ("delivered", "in_use", "picked_up")
                and rec.reservation_block_end
                and rec.reservation_block_end < now
                and not rec.actual_return_datetime)

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------
    def _find_conflicts(self):
        """Return overlapping blocking reservations for the same serial."""
        self.ensure_one()
        if not self.lot_id or self.state not in BLOCKING_STATES:
            return self.browse()
        if not (self.reservation_block_start and self.reservation_block_end):
            return self.browse()
        return self.search([
            ("id", "!=", self.id),
            ("lot_id", "=", self.lot_id.id),
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_start", "<", self.reservation_block_end),
            ("reservation_block_end", ">", self.reservation_block_start),
        ])

    @api.constrains("lot_id", "reservation_block_start",
                    "reservation_block_end", "state")
    def _check_serial_conflicts(self):
        for rec in self:
            conflicts = rec._find_conflicts()
            if conflicts:
                raise ValidationError(_(
                    "Serial '%(lot)s' is already booked in an overlapping "
                    "operational period by %(refs)s.",
                    lot=rec.lot_id.name,
                    refs=", ".join(conflicts.mapped("name"))))

    # ------------------------------------------------------------------
    # PostgreSQL exclusion constraint (true overlap protection)
    # ------------------------------------------------------------------
    def init(self):
        """Install a GiST exclusion constraint so the database itself rejects
        overlapping bookings of the same serial - safe under concurrency.

        ``@api.constrains`` cannot guarantee this across simultaneous
        transactions; the EXCLUDE constraint can.
        """
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        self.env.cr.execute("""
            SELECT 1 FROM pg_constraint
            WHERE conname = 'rental_serial_no_overlap'
        """)
        if not self.env.cr.fetchone():
            # NOTE: Odoo stores Datetime as `timestamp WITHOUT time zone`
            # (UTC-naive). `tstzrange` would force a session-timezone cast that
            # is only STABLE, which Postgres rejects in an index expression
            # ("functions in index expression must be marked IMMUTABLE").
            # `tsrange` over the naive timestamps is IMMUTABLE -> use it.
            self.env.cr.execute("""
                ALTER TABLE rental_serial_reservation
                ADD CONSTRAINT rental_serial_no_overlap
                EXCLUDE USING gist (
                    lot_id WITH =,
                    tsrange(reservation_block_start,
                            reservation_block_end, '[)') WITH &&
                )
                WHERE (
                    state IN ('soft_hold','reserved','prepared','picked_up',
                              'delivered','in_use','returned')
                    AND lot_id IS NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # State machine actions
    # ------------------------------------------------------------------
    def _require_lot(self):
        missing = self.filtered(lambda r: not r.lot_id)
        if missing:
            raise UserError(_(
                "A serial number must be assigned before reserving: %s",
                ", ".join(missing.mapped("name"))))

    def action_reserve(self):
        self._require_lot()
        # Lock the candidate rows to serialise concurrent assignment.
        self._lock_rows()
        self._check_serial_conflicts()
        self.write({"state": "reserved"})
        self._post_state_message(_("Reservation confirmed (serial blocked)."))

    def action_soft_hold(self):
        self._require_lot()
        self.write({
            "state": "soft_hold",
            "soft_hold_owner_id": self.env.uid,
        })

    def action_prepare(self):
        self.write({"state": "prepared"})

    def action_pickup(self):
        self.write({
            "state": "picked_up",
            "actual_pickup_datetime": fields.Datetime.now(),
        })

    def action_deliver(self):
        self.write({
            "state": "delivered",
            "actual_delivery_datetime": fields.Datetime.now(),
        })

    def action_set_in_use(self):
        self.write({"state": "in_use"})

    def action_return(self):
        self.write({
            "state": "returned",
            "actual_return_datetime": fields.Datetime.now(),
        })

    def action_release(self):
        for rec in self:
            if (rec.auto_release_policy == "on_return_validation"
                    and not rec.actual_return_datetime
                    and rec.state not in ("draft", "quotation", "cancelled")):
                raise UserError(_(
                    "Reservation %s cannot be released: its policy requires a "
                    "validated return first.", rec.name))
        self.write({
            "state": "released",
            "actual_release_datetime": fields.Datetime.now(),
        })
        self._post_state_message(_("Serial released and available again."))

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    def _post_state_message(self, body):
        for rec in self:
            rec.message_post(body=body)

    # ------------------------------------------------------------------
    # Serial change with validation (Case 4)
    # ------------------------------------------------------------------
    def action_change_serial(self, new_lot_id):
        self.ensure_one()
        new_lot = self.env["stock.lot"].browse(new_lot_id)
        if new_lot.product_id != self.product_id:
            raise UserError(_("The new serial does not belong to this product."))
        available = self.env["rental.availability.service"].get_available_serials(
            self.product_id.id, self.reservation_block_start,
            self.reservation_block_end, self.location_id.id or None,
            ignore_reservation_ids=self.ids)
        if new_lot not in available:
            raise UserError(_(
                "Serial '%s' is not available for this operational period.",
                new_lot.name))
        old_name = self.lot_id.name
        self.lot_id = new_lot
        self.message_post(body=_(
            "Serial changed from %(old)s to %(new)s.",
            old=old_name, new=new_lot.name))

    # ------------------------------------------------------------------
    # Concurrency helpers
    # ------------------------------------------------------------------
    def _lock_rows(self):
        if self.ids:
            self.env.cr.execute(
                "SELECT id FROM rental_serial_reservation WHERE id IN %s FOR UPDATE",
                (tuple(self.ids),))

    # ------------------------------------------------------------------
    # Inventory integration (Section 12): real serial pickings
    # ------------------------------------------------------------------
    def _rental_output_location(self):
        return self.env.ref("stock.stock_location_customers")

    def _warehouse_for(self, rec):
        if rec.warehouse_id:
            return rec.warehouse_id
        return self.env["stock.warehouse"].search(
            [("company_id", "=", rec.company_id.id)], limit=1)

    def _create_serial_picking(self, outgoing=True):
        """Create AND validate a real transfer carrying the reserved serials.

        Outgoing: warehouse stock -> customer location (delivery / install).
        Incoming: customer location -> warehouse stock (return).
        Groups by (company, warehouse, partner); one stock.move per product and
        one stock.move.line per serial so traceability matches Odoo natively.
        """
        Picking = self.env["stock.picking"]
        pickings = Picking.browse()
        groups = defaultdict(lambda: self.browse())
        for rec in self.filtered("lot_id"):
            groups[(rec.company_id.id, rec.warehouse_id.id, rec.partner_id.id)] |= rec
        for (company_id, _wh_id, partner_id), recs in groups.items():
            wh = self._warehouse_for(recs[0])
            stock_loc = recs[0].location_id or wh.lot_stock_id
            cust_loc = self._rental_output_location()
            if outgoing:
                src, dest, pick_type = stock_loc, cust_loc, wh.out_type_id
            else:
                src, dest, pick_type = cust_loc, stock_loc, wh.in_type_id
            picking = Picking.create({
                "picking_type_id": pick_type.id,
                "location_id": src.id,
                "location_dest_id": dest.id,
                "partner_id": partner_id,
                "company_id": company_id,
                "origin": recs[0].sale_order_id.name or recs[0].name,
            })
            by_product = defaultdict(lambda: self.browse())
            for rec in recs:
                by_product[rec.product_id] |= rec
            for product, prs in by_product.items():
                move = self.env["stock.move"].create({
                    "name": product.display_name,
                    "product_id": product.id,
                    "product_uom_qty": len(prs),
                    "product_uom": product.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": src.id,
                    "location_dest_id": dest.id,
                    "company_id": company_id,
                    "picked": True,  # 17+: marks the move quantities as done
                })
                for rec in prs:
                    self.env["stock.move.line"].create({
                        "move_id": move.id,
                        "picking_id": picking.id,
                        "product_id": product.id,
                        "lot_id": rec.lot_id.id,
                        "quantity": 1.0,
                        "product_uom_id": product.uom_id.id,
                        "location_id": src.id,
                        "location_dest_id": dest.id,
                        "picked": True,
                    })
            picking.action_confirm()
            picking._action_done()
            recs.write({"delivery_picking_id" if outgoing else "return_picking_id": picking.id})
            pickings |= picking
        return pickings

    def action_create_delivery_picking(self):
        pickings = self.filtered(
            lambda r: r.lot_id and not r.delivery_picking_id
        )._create_serial_picking(outgoing=True)
        self.write({"state": "delivered",
                    "actual_delivery_datetime": fields.Datetime.now()})
        for rec in self:
            rec.message_post(body=_("Delivery transfer %s validated.") % (
                rec.delivery_picking_id.name or ""))
        return self._picking_action(pickings)

    def action_create_return_picking(self):
        to_return = self.filtered(lambda r: r.lot_id and not r.return_picking_id)
        pickings = to_return._create_serial_picking(outgoing=False)
        self.write({"state": "returned",
                    "actual_return_datetime": fields.Datetime.now()})
        for rec in self:
            rec.message_post(body=_("Return transfer %s validated.") % (
                rec.return_picking_id.name or ""))
        return self._picking_action(pickings)

    def _picking_action(self, pickings):
        if not pickings:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "list,form" if len(pickings) > 1 else "form",
            "res_id": pickings.id if len(pickings) == 1 else False,
            "domain": [("id", "in", pickings.ids)],
            "name": _("Serial Transfers"),
        }

    # ------------------------------------------------------------------
    # Board / OWL data API (called from the planning board via orm.call,
    # and re-exposed by the JSON controllers in controllers/main.py).
    # Public @api.model methods on this accessible model so the frontend
    # does not depend on extra controller/registry plumbing.
    # ------------------------------------------------------------------
    @api.model
    def serial_timeline(self, date_start, date_end, product_ids=None,
                        warehouse_id=None, package_id=None, partner_id=None,
                        states=None):
        start = fields.Datetime.to_datetime(date_start)
        end = fields.Datetime.to_datetime(date_end)
        Product = self.env["product.product"]
        if package_id:
            pkg = self.env["rental.package.template"].browse(int(package_id))
            products = pkg.line_ids.mapped("product_id")
        elif product_ids:
            products = Product.browse(product_ids)
        else:
            products = Product.search([
                ("tracking", "=", "serial"),
                ("x_rental_serial_planning", "=", True)])
        lots = self.env["stock.lot"].search([("product_id", "in", products.ids)])

        res_domain = [
            ("lot_id", "in", lots.ids),
            ("reservation_block_start", "<", end),
            ("reservation_block_end", ">", start),
            ("state", "not in", ("cancelled",)),
        ]
        if partner_id:
            res_domain.append(("partner_id", "=", int(partner_id)))
        if warehouse_id:
            res_domain.append(("warehouse_id", "=", int(warehouse_id)))
        if states:
            res_domain.append(("state", "in", states))
        reservations = self.search(res_domain)

        dt_domain = [
            ("lot_id", "in", lots.ids),
            ("state", "in", ("scheduled", "in_progress")),
            ("start_datetime", "<", end),
            "|", ("end_datetime", "=", False), ("end_datetime", ">", start),
        ]
        downtimes = self.env["rental.serial.downtime"].search(dt_domain)

        res_by_lot = {}
        for r in reservations:
            res_by_lot.setdefault(r.lot_id.id, []).append({
                "id": r.id, "type": "reservation", "name": r.name,
                "state": r.state, "partner": r.partner_id.display_name,
                "sale_order_id": r.sale_order_id.id,
                "sale_order": r.sale_order_id.name,
                "billable_start": r.rental_billable_start and r.rental_billable_start.isoformat(),
                "billable_end": r.rental_billable_end and r.rental_billable_end.isoformat(),
                "start": r.reservation_block_start.isoformat(),
                "end": r.reservation_block_end.isoformat(),
                "conflict": r.conflict_status == "conflict",
            })
        dt_by_lot = {}
        for d in downtimes:
            dt_by_lot.setdefault(d.lot_id.id, []).append({
                "id": d.id, "type": "downtime", "name": d.name,
                "state": "maintenance", "reason": d.reason,
                "start": d.start_datetime.isoformat(),
                "end": (d.end_datetime or end).isoformat(),
                "conflict": False,
            })

        result = []
        for product in products:
            product_lots = lots.filtered(lambda l: l.product_id == product)
            serial_rows = []
            for lot in product_lots:
                serial_rows.append({
                    "lot_id": lot.id, "lot_name": lot.name,
                    "blocks": res_by_lot.get(lot.id, []) + dt_by_lot.get(lot.id, []),
                })
            result.append({
                "product_id": product.id,
                "product_name": product.display_name,
                "serial_count": len(product_lots),
                "serials": serial_rows,
            })
        return {
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "products": result,
            "blocking_states": list(BLOCKING_STATES),
        }

    @api.model
    def board_filters(self):
        env = self.env
        return {
            "warehouses": [{"id": w.id, "name": w.name}
                           for w in env["stock.warehouse"].search([])],
            "products": [{"id": p.id, "name": p.display_name}
                         for p in env["product.product"].search(
                             [("tracking", "=", "serial"),
                              ("x_rental_serial_planning", "=", True)])],
            "packages": [{"id": p.id, "name": p.display_name}
                         for p in env["rental.package.template"].search([])],
            "states": [{"key": k, "label": v}
                       for k, v in self._fields["state"].selection],
        }

    @api.model
    def release_reservations(self, reservation_ids):
        recs = self.browse(reservation_ids)
        recs.action_release()
        return {"released": recs.ids}

    @api.model
    def create_downtime_quick(self, lot_id, reason, start, end=None):
        dt = self.env["rental.serial.downtime"].create({
            "lot_id": int(lot_id),
            "reason": reason,
            "start_datetime": fields.Datetime.to_datetime(start),
            "end_datetime": fields.Datetime.to_datetime(end) if end else False,
        })
        return {"downtime_id": dt.id}

    # ------------------------------------------------------------------
    # Cron entry points
    # ------------------------------------------------------------------
    @api.model
    def _cron_expire_soft_holds(self):
        now = fields.Datetime.now()
        expired = self.search([
            ("state", "=", "soft_hold"),
            ("soft_hold_until", "!=", False),
            ("soft_hold_until", "<", now),
        ])
        for rec in expired:
            rec.message_post(body=_("Soft hold expired automatically; released."))
        expired.write({"state": "released",
                       "actual_release_datetime": now})

    @api.model
    def _cron_release_expired(self):
        now = fields.Datetime.now()
        # on_block_end -> release once the block period has elapsed.
        to_release = self.search([
            ("auto_release_policy", "=", "on_block_end"),
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_end", "<", now),
        ])
        for rec in to_release:
            rec.message_post(body=_("Auto-released on block end."))
        to_release.write({"state": "released", "actual_release_datetime": now})

        # Flag overdue items whose policy needs a real return.
        overdue = self.search([
            ("auto_release_policy", "!=", "on_block_end"),
            ("state", "in", ("delivered", "in_use", "picked_up")),
            ("reservation_block_end", "<", now),
            ("actual_return_datetime", "=", False),
        ])
        for rec in overdue:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Overdue rental return: %s") % rec.name,
                note=_("Serial %s should have been returned by %s.") % (
                    rec.lot_id.name, rec.reservation_block_end))
