# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class RentalSeason(models.Model):
    _name = "rental.season"
    _description = "Temporada de renta"
    _order = "priority, date_start"

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    priority = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)


class RentalEventType(models.Model):
    _name = "rental.event.type"
    _description = "Tipo de evento"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)


class RentalPricingRule(models.Model):
    _name = "rental.pricing.rule"
    _description = "Regla de precio de renta"
    _order = "priority, sequence, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    priority = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)

    scope = fields.Selection(
        [("global", "Global"), ("product", "Producto"), ("category", "Categoría"),
         ("package", "Paquete"), ("customer", "Cliente"), ("event_type", "Tipo de evento")],
        string="Alcance", default="global", required=True)
    product_id = fields.Many2one("product.product", string="Producto")
    category_id = fields.Many2one("product.category", string="Categoría")
    package_id = fields.Many2one("rental.package.template", string="Paquete")
    partner_id = fields.Many2one("res.partner", string="Cliente")
    event_type_id = fields.Many2one("rental.event.type", string="Tipo de evento")

    date_start = fields.Date(string="Desde")
    date_end = fields.Date(string="Hasta")
    season_id = fields.Many2one("rental.season", string="Temporada")
    weekdays = fields.Char(string="Días de semana", help="0=Lun … 6=Dom, separados por coma (p. ej. 5,6).")
    min_duration_hours = fields.Float(string="Duración mín. (h)")
    max_duration_hours = fields.Float(string="Duración máx. (h)")
    min_qty = fields.Float(string="Cantidad mín.")
    max_qty = fields.Float(string="Cantidad máx.")

    pricing_method = fields.Selection(
        [("fixed", "Precio fijo"), ("percent_increase", "Incremento %"),
         ("percent_discount", "Descuento %"), ("amount_surcharge", "Cargo fijo"),
         ("amount_discount", "Descuento fijo"), ("multiplier", "Multiplicador")],
        string="Método", default="percent_increase", required=True)
    base = fields.Selection(
        [("product_price", "Precio del producto"), ("package_price", "Precio del paquete"),
         ("subtotal", "Subtotal"), ("duration", "Duración"), ("quantity", "Cantidad")],
        string="Base", default="product_price")
    value = fields.Float(string="Valor", required=True)
    apply_on = fields.Selection(
        [("rental_price", "Precio de renta"), ("delivery_fee", "Cargo de entrega"),
         ("cleaning_fee", "Cargo de limpieza"), ("damage_fee", "Cargo por daño"),
         ("late_fee", "Cargo por retraso"), ("whole_order", "Toda la orden")],
        string="Aplica a", default="rental_price", required=True)
    requires_manager_approval = fields.Boolean(string="Requiere autorización")
    description = fields.Char(string="Descripción")

    # ------------------------------------------------------------------
    def _scope_matches(self, product, package, partner, event_type, cat_ids):
        self.ensure_one()
        s = self.scope
        if s == "global":
            return True
        if s == "product":
            return bool(product) and self.product_id == product
        if s == "category":
            return bool(self.category_id) and self.category_id.id in cat_ids
        if s == "package":
            return bool(package) and self.package_id == package
        if s == "customer":
            return bool(partner) and self.partner_id == partner
        if s == "event_type":
            return bool(event_type) and self.event_type_id == event_type
        return False

    def _when_matches(self, when, duration_hours, qty):
        self.ensure_one()
        d = when.date() if when else None
        if self.date_start and d and d < self.date_start:
            return False
        if self.date_end and d and d > self.date_end:
            return False
        if self.season_id and d and not (
                self.season_id.date_start <= d <= self.season_id.date_end):
            return False
        if self.weekdays and when:
            wd = {int(x) for x in self.weekdays.split(",") if x.strip().isdigit()}
            if wd and when.weekday() not in wd:
                return False
        if self.min_duration_hours and duration_hours and duration_hours < self.min_duration_hours:
            return False
        if self.max_duration_hours and duration_hours and duration_hours > self.max_duration_hours:
            return False
        if self.min_qty and qty < self.min_qty:
            return False
        if self.max_qty and qty and qty > self.max_qty:
            return False
        return True

    def _apply_to(self, subtotal):
        self.ensure_one()
        m, v = self.pricing_method, self.value
        if m == "fixed":
            return v
        if m == "percent_increase":
            return subtotal + subtotal * v / 100.0
        if m == "percent_discount":
            return subtotal - subtotal * v / 100.0
        if m == "amount_surcharge":
            return subtotal + v
        if m == "amount_discount":
            return subtotal - v
        if m == "multiplier":
            return subtotal * v
        return subtotal

    @api.model
    def _matching(self, apply_on, product, package, partner, event_type,
                  when, duration_hours, qty):
        rules = self.search([
            ("active", "=", True),
            ("apply_on", "=", apply_on),
            ("company_id", "in", (self.env.company.id, False))])
        cat_ids = []
        if product and product.categ_id and product.categ_id.parent_path:
            cat_ids = [int(x) for x in product.categ_id.parent_path.split("/") if x]
        out = self.browse()
        for r in rules:
            if r._scope_matches(product, package, partner, event_type, cat_ids) \
                    and r._when_matches(when, duration_hours, qty):
                out |= r
        return out


class RentalPricingService(models.AbstractModel):
    _name = "rental.pricing.service"
    _description = "Motor de cálculo de precios de renta"

    @api.model
    def _line_duration_hours(self, line):
        start, end = line._get_billable_period()
        if start and end and end > start:
            return (end - start).total_seconds() / 3600.0
        return 0.0

    @api.model
    def compute_line_price(self, line):
        """Apply rental_price rules to a sale line; returns a breakdown."""
        qty = line.product_uom_qty or 1.0
        base_total = (line.product_id.lst_price or 0.0) * qty
        when = line._get_billable_period()[0] or fields.Datetime.now()
        dur = self._line_duration_hours(line)
        rules = self.env["rental.pricing.rule"]._matching(
            "rental_price", line.product_id, line.x_package_id,
            line.order_id.partner_id, line.order_id.x_event_type_id, when, dur, qty)
        subtotal = base_total
        applied = []
        needs_approval = False
        for r in rules:
            new = r._apply_to(subtotal)
            applied.append({"rule": r.name, "method": r.pricing_method,
                            "delta": round(new - subtotal, 2)})
            needs_approval = needs_approval or r.requires_manager_approval
            subtotal = new
        return {
            "base_price": round(base_total, 2),
            "subtotal": round(subtotal, 2),
            "unit": round(subtotal / qty, 4) if qty else round(subtotal, 4),
            "applied_rules": applied,
            "requires_approval": needs_approval,
        }

    @api.model
    def compute_order_pricing_summary(self, order):
        lines = order.order_line.filtered(
            lambda l: l.x_line_type in ("serial_rental", "quantity_rental")
            and not l.display_type)
        rows = []
        total = 0.0
        for line in lines:
            bd = self.compute_line_price(line)
            rows.append({"line": line.product_id.display_name, **bd})
            total += bd["subtotal"]
        return {"lines": rows, "rental_subtotal": round(total, 2)}

    @api.model
    def compute_late_return_fee(self, reservation):
        """Compute (and return) a late fee for an overdue serial reservation."""
        now = fields.Datetime.now()
        if not reservation.reservation_block_end or reservation.reservation_block_end >= now:
            return 0.0
        days_late = max(1, (now - reservation.reservation_block_end).days + 1)
        line = reservation.sale_order_line_id
        line_price = (line.price_subtotal if line else 0.0) or (
            reservation.product_id.lst_price or 0.0)
        rules = self.env["rental.pricing.rule"]._matching(
            "late_fee", reservation.product_id, reservation.package_id,
            reservation.partner_id, reservation.sale_order_id.x_event_type_id,
            now, 0.0, 1.0)
        fee = 0.0
        for r in rules:
            if r.pricing_method == "amount_surcharge":
                fee += r.value * days_late
            elif r.pricing_method == "percent_increase":
                fee += line_price * r.value / 100.0 * days_late
        return round(fee, 2)
