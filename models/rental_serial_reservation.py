# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .rental_availability_service import BLOCKING_STATES

_MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("quotation", "Cotización"),
    ("soft_hold", "Apartado temporal"),
    ("reserved", "Reservado"),
    ("prepared", "Preparado"),
    ("picked_up", "Retirado"),
    ("delivered", "Entregado"),
    ("in_use", "En uso"),
    ("returned", "Devuelto"),
    ("released", "Liberado"),
    ("cancelled", "Cancelado"),
]

# Forward flow used by the action buttons.
_FORWARD = ["reserved", "prepared", "picked_up", "delivered",
            "in_use", "returned", "released"]


class RentalSerialReservation(models.Model):
    _name = "rental.serial.reservation"
    _description = "Reserva por número de serie"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "reservation_block_start desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        index=True, default=lambda self: _("Nuevo"))
    state = fields.Selection(
        STATE_SELECTION, string="Estado", default="draft", required=True,
        tracking=True, index=True)

    # Commercial links
    sale_order_id = fields.Many2one(
        "sale.order", string="Pedido de venta", index=True, ondelete="cascade")
    sale_order_line_id = fields.Many2one(
        "sale.order.line", string="Línea del pedido", index=True, ondelete="cascade")
    package_id = fields.Many2one("rental.package.template", string="Paquete")
    package_line_id = fields.Many2one("rental.package.template.line", string="Línea de paquete")
    partner_id = fields.Many2one("res.partner", string="Cliente", tracking=True)

    # Inventory links
    product_id = fields.Many2one(
        "product.product", string="Producto", required=True, index=True,
        domain="[('tracking', '=', 'serial')]")
    lot_id = fields.Many2one(
        "stock.lot", string="Número de serie", index=True,
        domain="[('product_id', '=', product_id)]", tracking=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén")
    location_id = fields.Many2one("stock.location", string="Ubicación origen")
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, index=True,
        default=lambda self: self.env.company)
    quantity = fields.Float(string="Cantidad", default=1.0)

    # Billable period (what the customer pays)
    rental_billable_start = fields.Datetime(string="Inicio facturable", tracking=True)
    rental_billable_end = fields.Datetime(string="Fin facturable", tracking=True)

    # Operational block period (what really blocks inventory)
    reservation_block_start = fields.Datetime(
        string="Inicio de bloqueo", required=True, index=True, tracking=True)
    reservation_block_end = fields.Datetime(
        string="Fin de bloqueo", required=True, index=True, tracking=True)

    # Real-world stamps
    actual_pickup_datetime = fields.Datetime(string="Retiro real")
    actual_delivery_datetime = fields.Datetime(string="Entrega real")
    actual_return_datetime = fields.Datetime(string="Devolución real")
    actual_release_datetime = fields.Datetime(string="Liberación real")

    auto_release_policy = fields.Selection(
        [("on_block_end", "Automática al fin del bloqueo"),
         ("on_return_validation", "Al validar la devolución"),
         ("manual_only", "Solo manual")],
        string="Política de liberación", default="on_return_validation", required=True)

    # Soft hold
    soft_hold_until = fields.Datetime(string="Apartado hasta")
    soft_hold_owner_id = fields.Many2one("res.users", string="Responsable del apartado")
    soft_hold_reason = fields.Char(string="Motivo del apartado")

    conflict_status = fields.Selection(
        [("ok", "OK"), ("conflict", "Conflicto")],
        string="Conflicto", compute="_compute_conflict_status", store=True)
    availability_status = fields.Selection(
        [("available", "Disponible"), ("blocked", "Bloqueado")],
        string="Disponibilidad", default="available")
    is_overdue = fields.Boolean(
        string="Atrasado", compute="_compute_is_overdue", store=False)
    notes = fields.Text(string="Notas")

    # Inventory integration (Section 12)
    delivery_picking_id = fields.Many2one(
        "stock.picking", string="Transferencia de entrega", copy=False, readonly=True)
    return_picking_id = fields.Many2one(
        "stock.picking", string="Transferencia de retorno", copy=False, readonly=True)
    substitution_log_ids = fields.One2many(
        "rental.serial.substitution.log", "reservation_id", string="Sustituciones")
    substitution_count = fields.Integer(compute="_compute_substitution_count")

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
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.serial.reservation") or _("Nuevo")
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
                    "La serie '%(lot)s' ya está reservada en un periodo "
                    "operativo que se empalma por %(refs)s.",
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
                "Debe asignarse un número de serie antes de reservar: %s",
                ", ".join(missing.mapped("name"))))

    def action_reserve(self):
        self._require_lot()
        # Lock the candidate rows to serialise concurrent assignment.
        self._lock_rows()
        self._check_serial_conflicts()
        self.write({"state": "reserved"})
        self._post_state_message(_("Reserva confirmada (serie bloqueada)."))

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
                    "La reserva %s no puede liberarse: su política requiere "
                    "primero una devolución validada.", rec.name))
        self.write({
            "state": "released",
            "actual_release_datetime": fields.Datetime.now(),
        })
        self._post_state_message(_("Serie liberada y disponible nuevamente."))

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    def _post_state_message(self, body):
        for rec in self:
            rec.message_post(body=body)

    def _compute_substitution_count(self):
        data = self.env["rental.serial.substitution.log"]._read_group(
            [("reservation_id", "in", self.ids)], ["reservation_id"], ["__count"])
        mapped = {r.id: c for r, c in data if r}
        for rec in self:
            rec.substitution_count = mapped.get(rec.id, 0)

    def action_report_damage(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Reportar daño / faltante"),
            "res_model": "rental.damage.report", "view_mode": "form", "target": "new",
            "context": {
                "default_reservation_id": self.id,
                "default_product_id": self.product_id.id,
                "default_lot_id": self.lot_id.id,
                "default_sale_order_id": self.sale_order_id.id,
                "default_replacement_value": self.product_id.lst_price,
            },
        }

    def action_open_substitution(self):
        """Open the 'substitute serial' wizard for this reservation."""
        self.ensure_one()
        if not self.lot_id:
            raise UserError(_("Asigna una serie antes de poder sustituirla."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Sustituir serie"),
            "res_model": "rental.serial.substitution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_reservation_id": self.id, "active_id": self.id},
        }

    # ------------------------------------------------------------------
    # Serial change with validation (Case 4)
    # ------------------------------------------------------------------
    def action_change_serial(self, new_lot_id):
        self.ensure_one()
        new_lot = self.env["stock.lot"].browse(new_lot_id)
        if new_lot.product_id != self.product_id:
            raise UserError(_("La nueva serie no pertenece a este producto."))
        available = self.env["rental.availability.service"].get_available_serials(
            self.product_id.id, self.reservation_block_start,
            self.reservation_block_end, self.location_id.id or None,
            ignore_reservation_ids=self.ids)
        if new_lot not in available:
            raise UserError(_(
                "La serie '%s' no está disponible para este periodo operativo.",
                new_lot.name))
        old_name = self.lot_id.name
        self.lot_id = new_lot
        self.message_post(body=_(
            "Serie cambiada de %(old)s a %(new)s.",
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
            rec.message_post(body=_("Transferencia de entrega %s validada.") % (
                rec.delivery_picking_id.name or ""))
        return self._picking_action(pickings)

    def action_create_return_picking(self):
        to_return = self.filtered(lambda r: r.lot_id and not r.return_picking_id)
        pickings = to_return._create_serial_picking(outgoing=False)
        self.write({"state": "returned",
                    "actual_return_datetime": fields.Datetime.now()})
        for rec in self:
            rec.message_post(body=_("Transferencia de retorno %s validada.") % (
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
            "name": _("Transferencias por serie"),
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
                "product_name": r.product_id.name,
                "lot_name": r.lot_id.name,
                "billable_start": r.rental_billable_start and r.rental_billable_start.isoformat(),
                "billable_end": r.rental_billable_end and r.rental_billable_end.isoformat(),
                "start": r.reservation_block_start.isoformat(),
                "end": r.reservation_block_end.isoformat(),
                "conflict": r.conflict_status == "conflict",
                "overdue": r.is_overdue,
            })
        dt_by_lot = {}
        for d in downtimes:
            dt_by_lot.setdefault(d.lot_id.id, []).append({
                "id": d.id, "type": "downtime", "name": d.name,
                "state": "maintenance", "reason": d.reason,
                "lot_name": d.lot_id.name,
                "product_name": d.product_id.name,
                "start": d.start_datetime.isoformat(),
                "end": (d.end_datetime or end).isoformat(),
                "open_ended": not d.end_datetime,
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
                "product_name": product.name,
                "sku": product.default_code or "",
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
    def planning_dashboard(self, days=30):
        """Aggregated KPIs for the planning / rental-management dashboard.

        Everything respects the selected ``days`` horizon. Lists are grouped by
        record id (and merged by display name) so no duplicates appear.
        """
        now = fields.Datetime.now()
        horizon = now + timedelta(days=days)
        Lot = self.env["stock.lot"]
        Downtime = self.env["rental.serial.downtime"]
        ops_states = ["soft_hold", "reserved", "prepared", "picked_up", "delivered", "in_use"]

        products = self.env["product.product"].search([
            ("tracking", "=", "serial"), ("x_rental_serial_planning", "=", True)])
        lots = Lot.search([("product_id", "in", products.ids)])
        total_serials = len(lots)

        # --- snapshot "now" ---
        res_now = self.search([
            ("state", "in", ops_states),
            ("reservation_block_start", "<=", now),
            ("reservation_block_end", ">", now),
        ])
        dt_now = Downtime.search([
            ("state", "in", ["scheduled", "in_progress"]),
            ("start_datetime", "<=", now),
            "|", ("end_datetime", "=", False), ("end_datetime", ">", now),
        ])
        maint_lots = set(dt_now.mapped("lot_id").ids)
        blocked_lots = set(res_now.mapped("lot_id").ids) - maint_lots
        blocked_now = len(blocked_lots)
        maint_now = len(maint_lots)
        available_now = max(total_serials - blocked_now - maint_now, 0)
        utilization = round(100 * blocked_now / total_serials) if total_serials else 0

        # --- counters (horizon-aware where it makes sense) ---
        active_reservations = self.search_count([
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_start", "<", horizon),
            ("reservation_block_end", ">", now)])
        conflicts = self.search_count([("conflict_status", "=", "conflict")])
        soft_holds = self.search_count([("state", "=", "soft_hold")])
        soft_expiring = self.search_count([
            ("state", "=", "soft_hold"), ("soft_hold_until", "!=", False),
            ("soft_hold_until", "<", now + timedelta(hours=2))])
        overdue = self.search_count([
            ("state", "in", ["picked_up", "delivered", "in_use"]),
            ("reservation_block_end", "<", now),
            ("actual_return_datetime", "=", False)])
        returns_pending = self.search_count([("state", "=", "returned")])
        deliveries_7d = self.search_count([
            ("state", "in", ["reserved", "prepared", "picked_up"]),
            ("reservation_block_start", ">=", now),
            ("reservation_block_start", "<=", now + timedelta(days=7))])
        returns_7d = self.search_count([
            ("state", "in", ["delivered", "in_use", "picked_up"]),
            ("reservation_block_end", ">=", now),
            ("reservation_block_end", "<=", now + timedelta(days=7))])
        damaged_lost = Downtime.search_count([
            ("reason", "in", ["damaged", "lost"]),
            ("state", "in", ["scheduled", "in_progress"])])

        ShortageNeed = self.env["rental.shortage.need"]
        shortage_open = ShortageNeed.search_count([("state", "not in", ["sourced", "cancelled"])])
        shortage_pending = ShortageNeed.search_count([("state", "=", "pending")])
        sqg = ShortageNeed._read_group(
            [("state", "not in", ["sourced", "cancelled"])], [], ["shortage_qty:sum"])
        shortage_qty_total = (sqg[0][0] or 0.0) if sqg else 0.0
        overrides_pending = self.env["sale.order.line"].search_count(
            [("x_price_override_status", "=", "pending")])
        docs_pending_sign = self.env["rental.document.instance"].search_count(
            [("state", "in", ["generated", "sent"])])
        damage_open = self.env["rental.damage.report"].search_count(
            [("state", "not in", ["charged", "cancelled"])])

        # --- reservations by state (with %) ---
        sel = dict(self._fields["state"].selection)
        sg = self._read_group([
            ("state", "!=", "cancelled"),
            ("reservation_block_start", "<", horizon),
            ("reservation_block_end", ">", now)], ["state"], ["__count"])
        by_state = {st: cnt for st, cnt in sg}
        states_order = ["quotation", "soft_hold", "reserved", "prepared", "picked_up",
                        "delivered", "in_use", "returned", "released"]
        total_state = sum(by_state.get(s, 0) for s in states_order) or 0
        reservations_by_state = [{
            "key": s, "label": sel[s], "count": by_state.get(s, 0),
            "pct": round(100 * by_state.get(s, 0) / total_state) if total_state else 0,
        } for s in states_order if by_state.get(s, 0)]

        # --- demand: next 8 weeks (items blocked overlapping each week) ---
        end56 = now + timedelta(days=56)
        demand_recs = self.search([
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_end", ">", now),
            ("reservation_block_start", "<", end56)])
        demand = []
        for i in range(8):
            ws = now + timedelta(days=7 * i)
            we = ws + timedelta(days=7)
            inweek = demand_recs.filtered(
                lambda r: r.reservation_block_start < we and r.reservation_block_end > ws)
            cnt = len(inweek)
            custs = len(set(inweek.mapped("partner_id").ids))
            pctw = round(100 * cnt / total_serials) if total_serials else 0
            demand.append({
                "label": "%d %s" % (ws.day, _MONTHS_ES[ws.month - 1]),
                "week_index": i, "count": cnt, "customers": custs,
                "pct": min(pctw, 100),
                "level": "high" if pctw >= 66 else "mid" if pctw >= 33 else "low",
            })

        # --- top products in horizon (grouped by product, merged by name) ---
        recs_h = self.search([
            ("state", "not in", ["cancelled", "released"]),
            ("reservation_block_start", "<", horizon),
            ("reservation_block_end", ">", now)])
        by_name_p = {}
        for r in recs_h:
            e = by_name_p.setdefault(r.product_id.name or "—",
                                     {"name": r.product_id.name or "—", "count": 0,
                                      "product_id": r.product_id.id, "_orders": set()})
            e["count"] += 1
            if r.sale_order_id:
                e["_orders"].add(r.sale_order_id.id)
        products_list = sorted(by_name_p.values(), key=lambda x: -x["count"])
        for e in products_list:
            e["orders"] = len(e.pop("_orders"))
        top_products = products_list[:8]
        products_more = max(len(products_list) - 8, 0)

        # --- top customers (grouped by partner) ---
        recs_c = self.search([("state", "!=", "cancelled"), ("partner_id", "!=", False)])
        cust = {}
        for r in recs_c:
            d = cust.setdefault(r.partner_id.id, {
                "name": r.partner_id.name, "partner_id": r.partner_id.id,
                "count": 0, "items": 0, "value": 0.0})
            d["count"] += 1
            if r.state in BLOCKING_STATES:
                d["items"] += 1

        # --- event orders / value (within the period) ---
        event_orders = self.env["sale.order"].search([
            ("x_is_event_rental", "=", True),
            ("x_event_start", "<=", horizon), ("x_event_end", ">=", now)])
        for o in event_orders:
            if o.partner_id.id in cust:
                cust[o.partner_id.id]["value"] += o.amount_total
        top_customers = sorted(cust.values(), key=lambda x: -x["count"])[:8]
        customers_more = max(len(cust) - 8, 0)

        events_value = sum(event_orders.mapped("amount_total"))
        prev_orders = self.env["sale.order"].search([
            ("x_is_event_rental", "=", True),
            ("x_event_start", "<=", now), ("x_event_end", ">=", now - timedelta(days=days))])
        events_value_prev = sum(prev_orders.mapped("amount_total"))
        events_delta = (round(100 * (events_value - events_value_prev) / events_value_prev)
                        if events_value_prev else None)

        # --- utilization by product (now) ---
        lg = self._read_group([("product_id", "in", products.ids)], ["product_id"], ["__count"])
        lots_per_product = {p.id: c for p, c in lg if p}
        prod_blocked = {}
        seen = set()
        for rec in res_now:
            if rec.lot_id.id in seen or rec.lot_id.id in maint_lots:
                continue
            seen.add(rec.lot_id.id)
            prod_blocked[rec.product_id.id] = prod_blocked.get(rec.product_id.id, 0) + 1
        util_by_product = []
        for p in products:
            tot = lots_per_product.get(p.id, 0)
            if not tot:
                continue
            bl = prod_blocked.get(p.id, 0)
            util_by_product.append({
                "name": p.name, "product_id": p.id, "total": tot, "blocked": bl,
                "available": tot - bl, "pct": round(100 * bl / tot)})
        util_by_product = sorted(util_by_product, key=lambda x: -x["pct"])[:8]

        return {
            "generated": "%d %s %d, %02d:%02d" % (
                now.day, _MONTHS_ES[now.month - 1], now.year, now.hour, now.minute),
            "currency": self.env.company.currency_id.symbol or "",
            "days": days,
            "headline": {
                "total_serials": total_serials,
                "available_now": available_now,
                "blocked_now": blocked_now,
                "maint_now": maint_now,
                "utilization": utilization,
                "active_reservations": active_reservations,
                "overdue": overdue,
                "conflicts": conflicts,
                "soft_holds": soft_holds,
                "soft_expiring": soft_expiring,
                "returns_pending": returns_pending,
                "deliveries_7d": deliveries_7d,
                "returns_7d": returns_7d,
                "damaged_lost": damaged_lost,
                "upcoming_events": len(event_orders),
                "events_value": events_value,
                "events_delta": events_delta,
                "shortage_open": shortage_open,
                "shortage_pending": shortage_pending,
                "shortage_qty_total": round(shortage_qty_total),
                "overrides_pending": overrides_pending,
                "docs_pending_sign": docs_pending_sign,
                "damage_open": damage_open,
            },
            "reservations_by_state": reservations_by_state,
            "demand": demand,
            "top_products": top_products,
            "products_more": products_more,
            "top_customers": top_customers,
            "customers_more": customers_more,
            "util_by_product": util_by_product,
        }

    @api.model
    def commercial_reports(self, days=90):
        """Aggregated commercial analytics (Section 12)."""
        now = fields.Datetime.now()
        horizon = now + timedelta(days=days)
        past = now - timedelta(days=days)
        Downtime = self.env["rental.serial.downtime"]
        Damage = self.env["rental.damage.report"]

        products = self.env["product.product"].search([
            ("tracking", "=", "serial"), ("x_rental_serial_planning", "=", True)])
        lots = self.env["stock.lot"].search([("product_id", "in", products.ids)])
        lots_by_product = defaultdict(list)
        for lot in lots:
            lots_by_product[lot.product_id.id].append(lot)

        # blocked now (per product / per lot)
        res_now = self.search([
            ("state", "in", ["soft_hold", "reserved", "prepared", "picked_up", "delivered", "in_use"]),
            ("reservation_block_start", "<=", now), ("reservation_block_end", ">", now)])
        blocked_lots_now = set(res_now.mapped("lot_id").ids)

        # one pass over reservations in the window for revenue / counts
        res = self.search([
            ("state", "not in", ["cancelled"]),
            ("reservation_block_start", "<", horizon),
            ("reservation_block_end", ">", past)])
        line_n = {}
        lot_rev, lot_cnt, lot_days = defaultdict(float), defaultdict(int), defaultdict(float)
        prod_rev, prod_cnt = defaultdict(float), defaultdict(int)
        prod_last = {}
        pkg_orders, pkg_rev = defaultdict(set), defaultdict(float)
        for r in res:
            line = r.sale_order_line_id
            if line and line.id not in line_n:
                line_n[line.id] = len(line.x_serial_reservation_ids.filtered(
                    lambda x: x.state not in ("cancelled", "released"))) or 1
            share = (line.price_subtotal / line_n[line.id]) if line else 0.0
            lid, pid = r.lot_id.id, r.product_id.id
            lot_rev[lid] += share
            lot_cnt[lid] += 1
            prod_rev[pid] += share
            prod_cnt[pid] += 1
            if r.reservation_block_start and r.reservation_block_end:
                lot_days[lid] += (r.reservation_block_end - r.reservation_block_start).total_seconds() / 86400.0
            if r.reservation_block_start:
                prod_last[pid] = max(prod_last.get(pid, r.reservation_block_start), r.reservation_block_start)
            if r.package_id:
                pkg_orders[r.package_id.id].add(r.sale_order_id.id)
                pkg_rev[r.package_id.id] += share

        # downtime / damage per lot & product
        dt = Downtime.search([("lot_id", "in", lots.ids)])
        lot_damage, lot_lost, lot_maint = defaultdict(int), defaultdict(int), defaultdict(int)
        for d in dt:
            if d.reason in ("damaged",):
                lot_damage[d.lot_id.id] += 1
            elif d.reason in ("lost",):
                lot_lost[d.lot_id.id] += 1
            elif d.reason in ("maintenance", "repair", "cleaning"):
                lot_maint[d.lot_id.id] += 1
        dmg = Damage.search([("lot_id", "in", lots.ids)])
        lot_dmg_charge = defaultdict(float)
        prod_shortage = defaultdict(int)
        for x in dmg:
            lot_dmg_charge[x.lot_id.id] += x.suggested_charge or 0.0
        for n in self.env["rental.shortage.need"].search(
                [("product_id", "in", products.ids), ("state", "not in", ["cancelled", "sourced"])]):
            prod_shortage[n.product_id.id] += 1

        def _ceil(x):
            return int(x) + (1 if x > int(x) else 0)

        # --- product classification (12.1 / 12.2 / 12.9) ---
        classification = []
        for p in products:
            total = len(lots_by_product.get(p.id, []))
            blocked = len([l for l in lots_by_product.get(p.id, []) if l.id in blocked_lots_now])
            util = round(100 * blocked / total) if total else 0
            cnt = prod_cnt.get(p.id, 0)
            rev = prod_rev.get(p.id, 0.0)
            sc = prod_shortage.get(p.id, 0)
            last = prod_last.get(p.id)
            recent = bool(last and last >= past)
            if util >= 80 or sc >= 2:
                status, reason, suggest = "saturated", "Alta utilización / shortage frecuente", _ceil(total * 0.25)
            elif sc >= 1:
                status, reason, suggest = "shortage_risk", "Riesgo de faltante futuro", _ceil(total * 0.15)
            elif not recent:
                status, reason, suggest = "dead_stock", "Sin reservas en el periodo", 0
            elif cnt <= max(1, _ceil(total * 0.15)):
                status, reason, suggest = "low_rotation", "Baja rotación", 0
            else:
                status, reason, suggest = "healthy", "Rotación saludable", 0
            classification.append({
                "product": p.name, "total": total, "utilization": util,
                "reservations": cnt, "revenue": round(rev), "shortage_count": sc,
                "status": status, "reason": reason, "suggested_purchase": suggest})
        classification.sort(key=lambda x: (-x["utilization"], -x["reservations"]))

        # --- revenue per serial (12.3) ---
        revenue_by_serial = []
        for lot in lots:
            rev = lot_rev.get(lot.id, 0.0)
            if rev <= 0 and lot_cnt.get(lot.id, 0) == 0:
                continue
            dmgc = lot_damage.get(lot.id, 0)
            revenue_by_serial.append({
                "lot": lot.name, "product": lot.product_id.name,
                "reservations": lot_cnt.get(lot.id, 0), "revenue": round(rev),
                "days_blocked": round(lot_days.get(lot.id, 0.0), 1),
                "damage_count": dmgc,
                "score": round(rev / (1 + dmgc))})
        revenue_by_serial.sort(key=lambda x: -x["revenue"])
        revenue_by_serial = revenue_by_serial[:15]

        # --- damage per serial (12.4) ---
        damage_by_serial = []
        for lot in lots:
            risk = lot_damage.get(lot.id, 0) * 3 + lot_lost.get(lot.id, 0) * 5 + lot_maint.get(lot.id, 0)
            if risk == 0:
                continue
            damage_by_serial.append({
                "lot": lot.name, "product": lot.product_id.name,
                "damage": lot_damage.get(lot.id, 0), "lost": lot_lost.get(lot.id, 0),
                "maintenance": lot_maint.get(lot.id, 0),
                "charges": round(lot_dmg_charge.get(lot.id, 0.0)), "risk": risk})
        damage_by_serial.sort(key=lambda x: -x["risk"])
        damage_by_serial = damage_by_serial[:15]

        # --- margin per event (12.5) ---
        orders = self.env["sale.order"].search([
            ("x_is_event_rental", "=", True),
            ("x_event_start", ">=", past), ("x_event_start", "<", horizon)])
        margin_by_event = []
        for o in orders:
            revenue = o.amount_untaxed
            cost = 0.0
            for l in o.order_line.filtered(lambda l: not l.display_type and l.product_id):
                cost += (l.product_id.standard_price or 0.0) * (l.product_uom_qty or 0.0)
            margin = revenue - cost
            margin_by_event.append({
                "order": o.name, "event": o.x_event_name or "",
                "partner": o.partner_id.display_name, "revenue": round(revenue),
                "cost": round(cost), "margin": round(margin),
                "margin_pct": round(100 * margin / revenue) if revenue else 0})
        margin_by_event.sort(key=lambda x: -x["revenue"])
        margin_by_event = margin_by_event[:15]

        # --- category utilization (12.7) ---
        cat_data = defaultdict(lambda: {"total": 0, "blocked": 0, "revenue": 0.0, "shortage": 0})
        for p in products:
            c = cat_data[p.categ_id.name or "—"]
            c["total"] += len(lots_by_product.get(p.id, []))
            c["blocked"] += len([l for l in lots_by_product.get(p.id, []) if l.id in blocked_lots_now])
            c["revenue"] += prod_rev.get(p.id, 0.0)
            c["shortage"] += prod_shortage.get(p.id, 0)
        category_utilization = []
        for name, c in cat_data.items():
            category_utilization.append({
                "category": name, "total": c["total"], "blocked": c["blocked"],
                "available": c["total"] - c["blocked"],
                "utilization": round(100 * c["blocked"] / c["total"]) if c["total"] else 0,
                "revenue": round(c["revenue"]), "shortage_count": c["shortage"]})
        category_utilization.sort(key=lambda x: -x["utilization"])

        # --- package profitability (12.6) ---
        package_profit = []
        for pkg in self.env["rental.package.template"].search([]):
            times = len(pkg_orders.get(pkg.id, set()))
            if not times:
                continue
            comp_cost = sum(
                (pl.product_id.standard_price or 0.0) * (pl.quantity or 0.0)
                for pl in pkg.line_ids if pl.product_id)
            rev = pkg_rev.get(pkg.id, 0.0)
            package_profit.append({
                "package": pkg.name, "times": times, "revenue": round(rev),
                "component_cost": round(comp_cost),
                "avg_margin": round(rev - comp_cost * times)})
        package_profit.sort(key=lambda x: -x["revenue"])

        # --- projected occupancy by week (12.8) ---
        total_serials = len(lots)
        projected = []
        for i in range(8):
            ws = now + timedelta(days=7 * i)
            we = ws + timedelta(days=7)
            week = res.filtered(
                lambda r: r.state in BLOCKING_STATES
                and r.reservation_block_start < we and r.reservation_block_end > ws)
            confirmed = len(week.filtered(lambda r: r.state in (
                "reserved", "prepared", "picked_up", "delivered", "in_use")))
            quotes = len(week.filtered(lambda r: r.state in ("quotation", "soft_hold")))
            blocked = len(set(week.mapped("lot_id").ids))
            util = round(100 * blocked / total_serials) if total_serials else 0
            projected.append({
                "label": "%d %s" % (ws.day, _MONTHS_ES[ws.month - 1]),
                "utilization": min(util, 100), "confirmed": confirmed,
                "quotes": quotes, "shortage_risk": util >= 85})

        return {
            "currency": self.env.company.currency_id.symbol or "",
            "days": days,
            "classification": classification,
            "revenue_by_serial": revenue_by_serial,
            "damage_by_serial": damage_by_serial,
            "margin_by_event": margin_by_event,
            "category_utilization": category_utilization,
            "package_profit": package_profit,
            "projected": projected,
        }

    @api.model
    def board_filters(self):
        env = self.env
        return {
            "warehouses": [{"id": w.id, "name": w.name}
                           for w in env["stock.warehouse"].search([])],
            "products": [{"id": p.id, "name": p.name}
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
            rec.message_post(body=_("Apartado temporal expirado automáticamente; liberado."))
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
            rec.message_post(body=_("Liberado automáticamente al fin del bloqueo."))
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
                summary=_("Devolución de renta atrasada: %s") % rec.name,
                note=_("La serie %s debió devolverse antes de %s.") % (
                    rec.lot_id.name, rec.reservation_block_end))
