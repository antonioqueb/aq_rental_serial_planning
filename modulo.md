## ./__init__.py
```py
from . import models
from . import wizard
from . import controllers
```

## ./__manifest__.py
```py
{
    "name": "AQ Rental Serial Planning",
    "version": "19.0.1.2.0",
    "category": "Sales/Rental",
    "summary": "Booqable-style serial-level rental planning, availability engine and "
               "timeline calendar on top of native Odoo Rental.",
    "description": """
AQ Rental Serial Planning
=========================

Adds a serial-number based reservation layer on top of the native Odoo Rental
application (``sale_renting``):

* Reserve specific ``stock.lot`` units instead of generic quantities.
* Separate *billable period* (what the customer pays) from the *operational
  block period* (what really blocks inventory: prep, delivery, use, pickup,
  cleaning, review).
* No double booking of the same serial on overlapping operational periods
  (enforced both at ORM level and with a PostgreSQL ``EXCLUDE`` constraint).
* Rental packages/bundles that explode into serial-tracked components.
* Availability engine per product / per serial / per package.
* Soft holds with automatic expiry, configurable auto-release policies.
* Downtime (maintenance / damage / lost) blocking availability.
* OWL timeline board (Booqable-like) with one row per serial.
""",
    "author": "AlphaQueb",
    "website": "https://alphaqueb.com",
    "license": "LGPL-3",
    "depends": [
        "sale_renting",
        "stock",
        "account",
        "web",
    ],
    "data": [
        "security/rental_security.xml",
        "security/ir.model.access.csv",
        "security/rental_record_rules.xml",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "wizard/rental_serial_assign_wizard_views.xml",
        "wizard/rental_sample_data_views.xml",
        "views/rental_serial_reservation_views.xml",
        "views/rental_package_views.xml",
        "views/rental_serial_downtime_views.xml",
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/stock_lot_views.xml",
        "views/rental_planning_board_views.xml",
        "views/rental_planning_menus.xml",
        "report/rental_logistics_report.xml",
        "data/load_sample_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "aq_rental_serial_planning/static/src/planning/planning_board.scss",
            "aq_rental_serial_planning/static/src/planning/planning_board.xml",
            "aq_rental_serial_planning/static/src/planning/planning_board.js",
            "aq_rental_serial_planning/static/src/dashboard/kpi_dashboard.scss",
            "aq_rental_serial_planning/static/src/dashboard/kpi_dashboard.xml",
            "aq_rental_serial_planning/static/src/dashboard/kpi_dashboard.js",
        ],
    },
    "application": True,
    "installable": True,
}
```

## ./controllers/__init__.py
```py
from . import main
```

## ./controllers/main.py
```py
# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


def _parse_dt(value):
    if not value:
        return None
    return fields.Datetime.to_datetime(value)


class RentalPlanningController(http.Controller):
    """JSON endpoints documented in the spec (Section 15).

    The OWL board itself talks to the model via ``orm.call`` (no extra JS
    dependencies), but these HTTP endpoints remain available and delegate to
    the same model methods so behaviour stays identical and single-sourced.
    """

    @http.route("/rental_serial_planning/serial_timeline", type="json", auth="user")
    def serial_timeline(self, date_start, date_end, product_ids=None, warehouse_id=None,
                        location_id=None, partner_id=None, states=None, package_id=None, **kw):
        return request.env["rental.serial.reservation"].serial_timeline(
            date_start, date_end, product_ids=product_ids, warehouse_id=warehouse_id,
            package_id=package_id, partner_id=partner_id, states=states)

    @http.route("/rental_serial_planning/filters", type="json", auth="user")
    def filters(self, **kw):
        return request.env["rental.serial.reservation"].board_filters()

    @http.route("/rental_serial_planning/release", type="json", auth="user")
    def release(self, reservation_ids, **kw):
        return request.env["rental.serial.reservation"].release_reservations(reservation_ids)

    @http.route("/rental_serial_planning/create_downtime", type="json", auth="user")
    def create_downtime(self, lot_id, reason, start, end=None, **kw):
        return request.env["rental.serial.reservation"].create_downtime_quick(
            lot_id, reason, start, end)

    # Availability lookups (kept on the service)
    @http.route("/rental_serial_planning/product_availability", type="json", auth="user")
    def product_availability(self, product_id, block_start, block_end, location_id=None, **kw):
        return request.env["rental.availability.service"].get_product_availability(
            int(product_id), _parse_dt(block_start), _parse_dt(block_end),
            int(location_id) if location_id else None)

    @http.route("/rental_serial_planning/package_availability", type="json", auth="user")
    def package_availability(self, package_id, block_start, block_end, location_id=None, **kw):
        return request.env["rental.availability.service"].get_package_availability(
            int(package_id), _parse_dt(block_start), _parse_dt(block_end),
            int(location_id) if location_id else None)

    @http.route("/rental_serial_planning/availability", type="json", auth="user")
    def availability(self, product_id, block_start, block_end, location_id=None, **kw):
        lots = request.env["rental.availability.service"].get_available_serials(
            int(product_id), _parse_dt(block_start), _parse_dt(block_end),
            int(location_id) if location_id else None)
        return [{"id": l.id, "name": l.name} for l in lots]
```

## ./data/ir_cron.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="cron_expire_soft_holds" model="ir.cron">
        <field name="name">Rental: Expire soft holds</field>
        <field name="model_id" ref="model_rental_serial_reservation"/>
        <field name="state">code</field>
        <field name="code">model._cron_expire_soft_holds()</field>
        <field name="interval_number">10</field>
        <field name="interval_type">minutes</field>
        <field name="active" eval="True"/>
    </record>

    <record id="cron_release_expired" model="ir.cron">
        <field name="name">Rental: Release expired reservations</field>
        <field name="model_id" ref="model_rental_serial_reservation"/>
        <field name="state">code</field>
        <field name="code">model._cron_release_expired()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">hours</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

## ./data/ir_sequence.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="seq_rental_serial_reservation" model="ir.sequence">
            <field name="name">Rental Serial Reservation</field>
            <field name="code">rental.serial.reservation</field>
            <field name="prefix">RSR/%(year)s/</field>
            <field name="padding">5</field>
            <field name="company_id" eval="False"/>
        </record>

        <record id="seq_rental_serial_downtime" model="ir.sequence">
            <field name="name">Rental Serial Downtime</field>
            <field name="code">rental.serial.downtime</field>
            <field name="prefix">DWN/%(year)s/</field>
            <field name="padding">5</field>
            <field name="company_id" eval="False"/>
        </record>
    </data>
</odoo>
```

## ./data/load_sample_data.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Runs on EVERY install and update (not noupdate), independent of the
         database demo flag. The method is idempotent: it only creates the
         dataset once (marker product AQ-SILLA) and never raises. -->
    <function model="rental.sample.data.wizard" name="_load_sample_data_auto"/>
</odoo>
```

## ./models/__init__.py
```py
from . import rental_availability_service
from . import product_template
from . import product_product
from . import rental_package
from . import rental_serial_reservation
from . import rental_serial_downtime
from . import stock_lot
from . import sale_order
from . import sale_order_line
```

## ./models/product_product.py
```py
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    x_serial_reservation_count = fields.Integer(
        string="Reservas por serie activas",
        compute="_compute_serial_reservation_count")

    def _compute_serial_reservation_count(self):
        data = self.env["rental.serial.reservation"]._read_group(
            [("product_id", "in", self.ids),
             ("state", "not in", ("cancelled", "released"))],
            ["product_id"], ["__count"])
        mapped = {product.id: count for product, count in data}
        for product in self:
            product.x_serial_reservation_count = mapped.get(product.id, 0)

    def action_open_serial_availability(self):
        """Smart-button: open the planning board pre-filtered to this product."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "aq_rental_planning_board",
            "name": _("Disponibilidad: %s") % self.display_name,
            "params": {"product_id": self.id},
        }
```

## ./models/product_template.py
```py
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_rental_serial_planning = fields.Boolean(
        string="Planeación de renta por serie",
        help="Activa la planeación de reservas por número de serie para este "
             "producto rentable.",
    )
    x_requires_serial_reservation = fields.Boolean(
        string="Requiere reserva por serie",
        help="Deben asignarse series específicas antes de poder confirmar la "
             "reserva. Implica seguimiento por número de serie.",
    )
    x_allow_auto_serial_assignment = fields.Boolean(
        string="Permitir asignación automática", default=True)
    x_allow_manual_serial_assignment = fields.Boolean(
        string="Permitir asignación manual", default=True)
    x_rental_package_eligible = fields.Boolean(
        string="Elegible para paquetes", default=True,
        help="Puede usarse como componente dentro de un paquete de renta.")

    # Default operational buffers (hours) used to derive the block period
    # from the billable period.
    x_default_preparation_hours = fields.Float(string="Preparación (h)", default=0.0)
    x_default_delivery_buffer_hours = fields.Float(string="Margen de entrega (h)", default=0.0)
    x_default_return_buffer_hours = fields.Float(string="Margen de retorno (h)", default=0.0)
    x_default_cleaning_hours = fields.Float(string="Limpieza/Revisión (h)", default=0.0)

    @api.constrains("x_requires_serial_reservation", "tracking")
    def _check_serial_tracking(self):
        for tmpl in self:
            if tmpl.x_requires_serial_reservation and tmpl.tracking != "serial":
                raise ValidationError(_(
                    "El producto '%s' requiere reserva por serie, así que su "
                    "seguimiento debe ser 'Por número de serie único'.",
                    tmpl.display_name))

    @api.onchange("x_requires_serial_reservation")
    def _onchange_requires_serial(self):
        if self.x_requires_serial_reservation:
            self.x_rental_serial_planning = True
            self.rent_ok = True
            if self.tracking != "serial":
                self.tracking = "serial"
```

## ./models/rental_availability_service.py
```py
# -*- coding: utf-8 -*-
"""Centralised availability engine.

This is an ``AbstractModel`` so it can be called from anywhere with
``self.env['rental.availability.service']`` without creating database rows.
It is the single source of truth for *what is available* in a given
operational block period, computed per serial (``stock.lot``) rather than
per generic quantity.
"""
from odoo import api, models, fields

# States in which a reservation actually blocks a serial.
BLOCKING_STATES = (
    "soft_hold",
    "reserved",
    "prepared",
    "picked_up",
    "delivered",
    "in_use",
    "returned",  # physically not back-and-released yet -> still blocks
)

# Downtime states that block a serial.
DOWNTIME_BLOCKING_STATES = ("scheduled", "in_progress")


class RentalAvailabilityService(models.AbstractModel):
    _name = "rental.availability.service"
    _description = "Motor de disponibilidad por serie"

    # ------------------------------------------------------------------
    # Low level helpers
    # ------------------------------------------------------------------
    @api.model
    def _normalise_period(self, block_start, block_end):
        if not block_start or not block_end:
            raise ValueError("An availability query requires a start and an end datetime.")
        if block_end <= block_start:
            raise ValueError("Operational block end must be after the start.")
        return block_start, block_end

    @api.model
    def _candidate_lots(self, product_id, location_id=None, company_id=None):
        """All serials that physically *could* be rented for a product.

        Filters: belongs to the product, not archived, currently in positive
        stock in an internal location. Maintenance/damage exclusion is handled
        through downtime records, not here, so historical lots stay queryable.
        """
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            return self.env["stock.lot"]

        domain = [("product_id", "=", product_id)]
        if company_id:
            domain.append(("company_id", "in", (company_id, False)))
        lots = self.env["stock.lot"].search(domain)

        # Keep only lots that have positive quantity in an internal location
        # (optionally restricted to a given location subtree).
        quant_domain = [
            ("lot_id", "in", lots.ids),
            ("quantity", ">", 0),
            ("location_id.usage", "=", "internal"),
        ]
        if location_id:
            location = self.env["stock.location"].browse(location_id)
            quant_domain.append(("location_id", "child_of", location.id))
        quants = self.env["stock.quant"]._read_group(
            quant_domain, ["lot_id"], []
        )
        lot_ids_with_stock = {lot.id for (lot,) in quants if lot}
        return lots.filtered(lambda l: l.id in lot_ids_with_stock)

    @api.model
    def _reserved_lot_ids(self, lot_ids, block_start, block_end, ignore_reservation_ids=None):
        """Lot ids blocked by an overlapping reservation in the period."""
        if not lot_ids:
            return set()
        domain = [
            ("lot_id", "in", list(lot_ids)),
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_start", "<", block_end),
            ("reservation_block_end", ">", block_start),
        ]
        if ignore_reservation_ids:
            domain.append(("id", "not in", list(ignore_reservation_ids)))
        groups = self.env["rental.serial.reservation"]._read_group(
            domain, ["lot_id"], []
        )
        return {lot.id for (lot,) in groups if lot}

    @api.model
    def _downtime_lot_ids(self, lot_ids, block_start, block_end):
        """Lot ids blocked by maintenance/damage/etc. in the period."""
        if not lot_ids:
            return set()
        domain = [
            ("lot_id", "in", list(lot_ids)),
            ("state", "in", list(DOWNTIME_BLOCKING_STATES)),
            ("start_datetime", "<", block_end),
            "|",
            ("end_datetime", "=", False),  # open-ended downtime blocks forever
            ("end_datetime", ">", block_start),
        ]
        groups = self.env["rental.serial.downtime"]._read_group(
            domain, ["lot_id"], []
        )
        return {lot.id for (lot,) in groups if lot}

    # ------------------------------------------------------------------
    # Public API - serials
    # ------------------------------------------------------------------
    @api.model
    def get_available_serials(self, product_id, block_start, block_end,
                              location_id=None, ignore_reservation_ids=None):
        """Recordset of ``stock.lot`` free for the whole operational period."""
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(
            candidates.ids, block_start, block_end, ignore_reservation_ids)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        blocked = reserved | down
        return candidates.filtered(lambda l: l.id not in blocked)

    @api.model
    def get_unavailable_serials(self, product_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(candidates.ids, block_start, block_end)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        blocked = reserved | down
        return candidates.filtered(lambda l: l.id in blocked)

    # ------------------------------------------------------------------
    # Public API - product summary
    # ------------------------------------------------------------------
    @api.model
    def get_product_availability(self, product_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(candidates.ids, block_start, block_end)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        available = candidates.filtered(lambda l: l.id not in (reserved | down))
        return {
            "product_id": product_id,
            "total_serials": len(candidates),
            "available_serials": available.ids,
            "reserved_serials": list(reserved),
            "unavailable_serials": list(down),
            "available_count": len(available),
            "reserved_count": len(reserved),
            "unavailable_count": len(down),
        }

    # ------------------------------------------------------------------
    # Public API - packages
    # ------------------------------------------------------------------
    @api.model
    def get_package_availability(self, package_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        package = self.env["rental.package.template"].browse(package_id)
        if not package.exists():
            return {"package_id": package_id, "max_packages": 0, "lines": []}

        line_results = []
        limits = []
        for line in package.line_ids.filtered(lambda l: l.required):
            product = line.product_id
            if product.tracking == "serial":
                avail = self.get_product_availability(
                    product.id, block_start, block_end, location_id)
                available_qty = avail["available_count"]
            else:
                # Non serial component: fall back to forecasted qty.
                available_qty = product.with_context(
                    to_date=block_start).free_qty
            possible = int(available_qty // line.quantity) if line.quantity else 0
            limits.append(possible)
            line_results.append({
                "line_id": line.id,
                "product_id": product.id,
                "product_name": product.display_name,
                "required_qty": line.quantity,
                "available_qty": available_qty,
                "possible_packages": possible,
                "is_limiting": False,
            })

        max_packages = min(limits) if limits else 0
        for res in line_results:
            res["is_limiting"] = res["possible_packages"] == max_packages
        return {
            "package_id": package_id,
            "package_name": package.display_name,
            "max_packages": max_packages,
            "lines": line_results,
        }
```

## ./models/rental_package.py
```py
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RentalPackageTemplate(models.Model):
    _name = "rental.package.template"
    _description = "Paquete / Bundle de renta"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="Nombre", required=True, tracking=True)
    code = fields.Char(string="Referencia interna", copy=False)
    active = fields.Boolean(string="Activo", default=True)
    description = fields.Text(string="Descripción")
    sale_product_id = fields.Many2one(
        "product.product", string="Producto comercial",
        help="Producto padre opcional que aparece como una sola línea en la "
             "cotización. Debe ser un producto de servicio/rentable que represente "
             "el paquete.")
    line_ids = fields.One2many(
        "rental.package.template.line", "package_id", string="Componentes",
        copy=True)
    pricing_policy = fields.Selection(
        [("sum_components", "Suma de componentes"),
         ("fixed_package_price", "Precio fijo del paquete"),
         ("discount_components", "Componentes con descuento")],
        string="Política de precio", default="sum_components", required=True)
    fixed_price = fields.Monetary(string="Precio fijo")
    hide_components_on_quote = fields.Boolean(string="Ocultar componentes en cotización")
    hide_components_on_invoice = fields.Boolean(string="Ocultar componentes en factura")
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        "res.currency", string="Moneda",
        default=lambda self: self.env.company.currency_id)

    component_count = fields.Integer(string="N° componentes",
                                     compute="_compute_component_count")

    @api.depends("line_ids")
    def _compute_component_count(self):
        for pkg in self:
            pkg.component_count = len(pkg.line_ids)

    @api.constrains("line_ids")
    def _check_has_lines(self):
        for pkg in self:
            if not pkg.line_ids:
                raise ValidationError(_("Un paquete debe contener al menos un componente."))

    def action_check_availability(self):
        """Open a transient summary of package availability (used by smart button)."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "aq_rental_planning_board",
            "name": _("Disponibilidad del paquete: %s") % self.display_name,
            "params": {"package_id": self.id},
        }


class RentalPackageTemplateLine(models.Model):
    _name = "rental.package.template.line"
    _description = "Componente de paquete de renta"
    _order = "sequence, id"

    package_id = fields.Many2one(
        "rental.package.template", string="Paquete", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Secuencia", default=10)
    product_id = fields.Many2one(
        "product.product", string="Producto", required=True,
        domain="[('x_rental_package_eligible', '=', True)]")
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
    required = fields.Boolean(string="Requerido", default=True)
    optional = fields.Boolean(
        string="Opcional",
        compute="_compute_optional", inverse="_inverse_optional", store=True)
    allow_substitution = fields.Boolean(string="Permitir sustitución")
    allowed_substitute_product_ids = fields.Many2many(
        "product.product", "rental_pkg_line_substitute_rel",
        "line_id", "product_id", string="Sustitutos")
    discount_percentage = fields.Float(string="Descuento %")
    tracking = fields.Selection(related="product_id.tracking", string="Seguimiento")
    notes = fields.Char(string="Notas")

    @api.depends("required")
    def _compute_optional(self):
        for line in self:
            line.optional = not line.required

    def _inverse_optional(self):
        for line in self:
            line.required = not line.optional

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad del componente debe ser positiva."))
```

## ./models/rental_serial_downtime.py
```py
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
```

## ./models/rental_serial_reservation.py
```py
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
```

## ./models/sale_order_line.py
```py
# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
```

## ./models/sale_order.py
```py
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
```

## ./models/stock_lot.py
```py
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class StockLot(models.Model):
    _inherit = "stock.lot"

    x_reservation_ids = fields.One2many(
        "rental.serial.reservation", "lot_id", string="Reservas")
    x_reservation_count = fields.Integer(string="N° reservas", compute="_compute_rental_counts")
    x_downtime_ids = fields.One2many(
        "rental.serial.downtime", "lot_id", string="Bloqueos")
    x_downtime_count = fields.Integer(string="N° bloqueos", compute="_compute_rental_counts")
    x_rental_revenue = fields.Monetary(
        string="Ingresos por renta", compute="_compute_rental_revenue",
        currency_field="x_currency_id")
    x_currency_id = fields.Many2one(
        "res.currency", compute="_compute_rental_revenue")

    def _compute_rental_counts(self):
        res_data = self.env["rental.serial.reservation"]._read_group(
            [("lot_id", "in", self.ids)], ["lot_id"], ["__count"])
        res_map = {lot.id: count for lot, count in res_data if lot}
        dt_data = self.env["rental.serial.downtime"]._read_group(
            [("lot_id", "in", self.ids)], ["lot_id"], ["__count"])
        dt_map = {lot.id: count for lot, count in dt_data if lot}
        for lot in self:
            lot.x_reservation_count = res_map.get(lot.id, 0)
            lot.x_downtime_count = dt_map.get(lot.id, 0)

    def _compute_rental_revenue(self):
        """Best-effort revenue attribution per serial via its order lines."""
        for lot in self:
            lot.x_currency_id = (lot.company_id or self.env.company).currency_id
            lines = lot.x_reservation_ids.mapped("sale_order_line_id")
            # Split each line's subtotal across the serials reserved on it.
            revenue = 0.0
            for line in lines:
                serials_on_line = len(line.x_serial_reservation_ids) or 1
                revenue += (line.price_subtotal or 0.0) / serials_on_line
            lot.x_rental_revenue = revenue

    def action_view_reservations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reservas: %s") % self.name,
            "res_model": "rental.serial.reservation",
            "view_mode": "list,form,calendar",
            "domain": [("lot_id", "=", self.id)],
            "context": {"default_lot_id": self.id,
                        "default_product_id": self.product_id.id},
        }
```

## ./report/rental_logistics_report.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Report action (appears in the Print menu of the Sale Order) -->
    <record id="action_report_rental_logistics" model="ir.actions.report">
        <field name="name">Hoja de Ruta Logística</field>
        <field name="model">sale.order</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">aq_rental_serial_planning.report_rental_logistics</field>
        <field name="report_file">aq_rental_serial_planning.report_rental_logistics</field>
        <field name="binding_model_id" ref="sale.model_sale_order"/>
        <field name="binding_type">report</field>
        <field name="print_report_name">'Ruta Logistica - %s' % (object.name)</field>
    </record>

    <!-- ================= TEMPLATE ================= -->
    <template id="report_rental_logistics">
        <t t-call="web.html_container">
            <t t-foreach="docs" t-as="o">
                <t t-call="web.basic_layout">
                    <div class="article" style="font-family:Helvetica,Arial,sans-serif;color:#0B1F2A;">

                        <!-- ===== AlphaQueb branded header ===== -->
                        <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
                            <tr>
                                <td style="vertical-align:middle;width:60px;">
                                    <div style="width:46px;height:46px;background-color:#0E7C86;border-radius:10px;
                                                color:#ffffff;text-align:center;line-height:46px;
                                                font-weight:bold;font-size:20px;letter-spacing:1px;">AQ</div>
                                </td>
                                <td style="vertical-align:middle;">
                                    <div style="font-weight:bold;letter-spacing:3px;font-size:13px;color:#0B1F2A;">
                                        ALPHA<span style="color:#0E7C86;">QUEB</span>
                                    </div>
                                    <div style="font-size:20px;font-weight:bold;color:#0E7C86;">Hoja de Ruta Logística</div>
                                </td>
                                <td style="vertical-align:middle;text-align:right;font-size:12px;color:#48606A;">
                                    <div style="font-size:16px;font-weight:bold;color:#0B1F2A;"><span t-field="o.name"/></div>
                                    <div><span t-field="o.partner_id"/></div>
                                    <div t-if="o.company_id"><span t-field="o.company_id.name"/></div>
                                </td>
                            </tr>
                        </table>
                        <div style="height:4px;background-color:#0E7C86;border-radius:3px;margin-bottom:16px;"></div>

                        <!-- ===== Event block ===== -->
                        <table style="width:100%;border-collapse:collapse;margin-bottom:14px;font-size:12px;">
                            <tr>
                                <td style="width:50%;vertical-align:top;padding-right:10px;">
                                    <div style="background-color:#F4F8F9;border:1px solid #E1ECEE;border-radius:8px;padding:12px;">
                                        <div style="font-weight:bold;color:#0E7C86;margin-bottom:6px;">EVENTO</div>
                                        <div><strong>Nombre:</strong> <span t-field="o.x_event_name"/></div>
                                        <div><strong>Ubicación:</strong> <span t-field="o.x_event_location"/></div>
                                        <div><strong>Cliente:</strong> <span t-field="o.partner_id"/></div>
                                        <div><strong>Inicio:</strong> <span t-field="o.x_event_start"/></div>
                                        <div><strong>Fin:</strong> <span t-field="o.x_event_end"/></div>
                                    </div>
                                </td>
                                <td style="width:50%;vertical-align:top;padding-left:10px;">
                                    <div style="background-color:#0B1F2A;border-radius:8px;padding:12px;color:#D7E6E9;">
                                        <div style="font-weight:bold;color:#19C3D6;margin-bottom:6px;">PERIODOS</div>
                                        <div style="margin-bottom:8px;">
                                            <div style="font-size:10px;color:#8FB4BB;">FACTURABLE (lo que se cobra)</div>
                                            <div><span t-field="o.x_billable_start"/> &#8594; <span t-field="o.x_billable_end"/></div>
                                        </div>
                                        <div>
                                            <div style="font-size:10px;color:#8FB4BB;">OPERATIVO / BLOQUEO (lo que ocupa inventario)</div>
                                            <div><span t-field="o.x_block_start"/> &#8594; <span t-field="o.x_block_end"/></div>
                                        </div>
                                    </div>
                                </td>
                            </tr>
                        </table>

                        <!-- ===== Serials roadmap ===== -->
                        <div style="font-weight:bold;color:#0E7C86;font-size:13px;margin:8px 0 6px;">
                            Unidades reservadas por número de serie
                        </div>
                        <table style="width:100%;border-collapse:collapse;font-size:11px;">
                            <thead>
                                <tr style="background-color:#0E7C86;color:#ffffff;">
                                    <th style="padding:6px;text-align:left;">Producto</th>
                                    <th style="padding:6px;text-align:left;">Serie</th>
                                    <th style="padding:6px;text-align:left;">Bloqueo inicio</th>
                                    <th style="padding:6px;text-align:left;">Bloqueo fin</th>
                                    <th style="padding:6px;text-align:left;">Estado</th>
                                    <th style="padding:6px;text-align:left;">Entrega</th>
                                    <th style="padding:6px;text-align:left;">Retorno</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr t-foreach="o._report_reservations()" t-as="r"
                                    t-att-style="'background-color:#F4F8F9;' if r_index % 2 else ''">
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;"><span t-field="r.product_id"/></td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;font-weight:bold;"><span t-field="r.lot_id.name"/></td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;"><span t-field="r.reservation_block_start"/></td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;"><span t-field="r.reservation_block_end"/></td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;"><span t-field="r.state"/></td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;color:#48606A;">
                                        <span t-if="r.delivery_picking_id" t-field="r.delivery_picking_id.name"/>
                                        <span t-else="">—</span>
                                    </td>
                                    <td style="padding:5px 6px;border-bottom:1px solid #E1ECEE;color:#48606A;">
                                        <span t-if="r.return_picking_id" t-field="r.return_picking_id.name"/>
                                        <span t-else="">—</span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>

                        <div t-if="not o._report_reservations()"
                             style="padding:14px;color:#90A4AB;font-size:12px;text-align:center;">
                            Sin reservas de serial registradas en esta orden.
                        </div>

                        <!-- ===== Logistics notes ===== -->
                        <div t-if="o.x_logistics_notes" style="margin-top:16px;">
                            <div style="font-weight:bold;color:#0E7C86;font-size:13px;margin-bottom:4px;">Notas logísticas</div>
                            <div style="font-size:11px;background-color:#F4F8F9;border:1px solid #E1ECEE;border-radius:8px;padding:10px;">
                                <span t-field="o.x_logistics_notes"/>
                            </div>
                        </div>

                        <!-- ===== Footer ===== -->
                        <div style="margin-top:26px;border-top:1px solid #E1ECEE;padding-top:8px;
                                    font-size:10px;color:#90A4AB;text-align:center;">
                            Generado por AlphaQueb · Rental Serial Planning · alphaqueb.com
                        </div>

                    </div>
                </t>
            </t>
        </t>
    </template>
</odoo>
```

## ./security/rental_record_rules.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <!-- Multi-company isolation -->
        <record id="rule_reservation_company" model="ir.rule">
            <field name="name">Reservation: multi-company</field>
            <field name="model_id" ref="model_rental_serial_reservation"/>
            <field name="global" eval="True"/>
            <field name="domain_force">['|',('company_id','=',False),('company_id','in',company_ids)]</field>
        </record>

        <record id="rule_downtime_company" model="ir.rule">
            <field name="name">Downtime: multi-company</field>
            <field name="model_id" ref="model_rental_serial_downtime"/>
            <field name="global" eval="True"/>
            <field name="domain_force">['|',('company_id','=',False),('company_id','in',company_ids)]</field>
        </record>

        <record id="rule_package_company" model="ir.rule">
            <field name="name">Package: multi-company</field>
            <field name="model_id" ref="model_rental_package_template"/>
            <field name="global" eval="True"/>
            <field name="domain_force">['|',('company_id','=',False),('company_id','in',company_ids)]</field>
        </record>

        <!-- Warehouse users may only release through managers: enforced in code,
             but restrict write on released state via a non-global rule example.
             (Release permission is gated in action_release / group access.) -->
    </data>
</odoo>
```

## ./security/rental_security.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- NOTE: Odoo 19 reworked res.groups and removed `category_id`
         (group categorisation moved to the privilege system). Groups are
         declared without it; they remain fully functional. -->
    <record id="group_rental_planner_user" model="res.groups">
        <field name="name">Renta / Planeador (Usuario)</field>
        <field name="comment">Ver calendario, consultar disponibilidad y crear reservas en borrador.</field>
    </record>

    <record id="group_rental_warehouse_user" model="res.groups">
        <field name="name">Renta / Almacén</field>
        <field name="implied_ids" eval="[(4, ref('group_rental_planner_user'))]"/>
        <field name="comment">Preparar, entregar, recibir equipo y escanear series.</field>
    </record>

    <record id="group_rental_planner_manager" model="res.groups">
        <field name="name">Renta / Planeador (Gerente)</field>
        <field name="implied_ids" eval="[(4, ref('group_rental_warehouse_user'))]"/>
        <field name="comment">Confirmar reservas, liberar series, resolver conflictos y editar periodos operativos.</field>
    </record>

    <record id="group_rental_administrator" model="res.groups">
        <field name="name">Renta / Administrador</field>
        <field name="implied_ids" eval="[(4, ref('group_rental_planner_manager'))]"/>
        <field name="comment">Configurar paquetes, políticas, márgenes y bloqueos.</field>
    </record>
</odoo>
```

## ./static/src/dashboard/kpi_dashboard.js
```js
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

// Shared semantic state palette (MUST match the planning board / calendar).
const STATE_COLORS = {
    draft: "#cbd5e1", quotation: "#94a3b8", soft_hold: "#f59e0b", reserved: "#38bdf8",
    prepared: "#7c3aed", picked_up: "#2563eb", delivered: "#10b981", in_use: "#15803d",
    returned: "#f97316", released: "#d1d5db", maintenance: "#4b5563", conflict: "#dc2626",
};

// ---- reusable formatting / classification helpers ----
function formatNumber(v) { return Number(v || 0).toLocaleString("es-MX", { maximumFractionDigits: 0 }); }
function getUtilizationStatus(p) {
    if (p < 20) return { label: "Utilización baja", cls: "is-low" };
    if (p < 60) return { label: "Utilización saludable", cls: "is-healthy" };
    if (p < 85) return { label: "Alta utilización", cls: "is-high" };
    return { label: "Riesgo de saturación", cls: "is-saturated" };
}
function getOccupancyLevel(p) {
    if (p >= 100) return "is-full";
    if (p >= 80) return "is-high";
    if (p >= 50) return "is-warning";
    return "is-normal";
}
function isoDay(d) { return d.toISOString().slice(0, 10); }
function serverNow() { return new Date().toISOString().slice(0, 19).replace("T", " "); }

export class RentalKpiDashboard extends Component {
    static template = "aq_rental_serial_planning.KpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, days: 30, data: null, clientBy: "count" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "rental.serial.reservation", "planning_dashboard", [], { days: this.state.days });
        } catch (e) {
            this.state.error = true;
        }
        this.state.loading = false;
    }
    setDays(d) { this.state.days = d; this.load(); }
    refresh() { this.load(); }

    // ---- formatting exposed to template ----
    fmt(v) { return formatNumber(v); }
    money(v) { return (this.state.data.currency || "") + formatNumber(v); }
    stateColor(key) { return STATE_COLORS[key] || "#cbd5e1"; }
    pct(value, max) { return max > 0 ? Math.round((value / max) * 100) : 0; }
    occLevel(p) { return getOccupancyLevel(p); }

    get ready() { return !this.state.loading && !!this.state.data; }
    get periodLabel() { return `Mostrando indicadores de los próximos ${this.state.days} días`; }

    get donutStyle() {
        const u = this.state.data.headline.utilization;
        return `background: conic-gradient(#C9A36A 0 ${u}%, #DCE5DC ${u}% 100%);`;
    }
    get utilStatus() { return getUtilizationStatus(this.state.data.headline.utilization); }

    // breakdown subtitle for "Reservas activas"
    get activeSubtitle() {
        const map = {};
        for (const s of this.state.data.reservations_by_state) map[s.key] = s.count;
        const parts = [];
        if (map.reserved) parts.push(`${map.reserved} reservadas`);
        if (map.prepared) parts.push(`${map.prepared} preparadas`);
        if (map.picked_up) parts.push(`${map.picked_up} retiradas`);
        if (map.delivered) parts.push(`${map.delivered} entregadas`);
        if (map.in_use) parts.push(`${map.in_use} en uso`);
        return parts.join(" · ") || "Sin reservas activas";
    }

    // ---- alert summary ----
    get alerts() {
        const h = this.state.data.headline;
        const out = [];
        if (h.conflicts) out.push({ key: "conflicts", icon: "fa-exclamation-triangle", level: "is-critical", text: `${h.conflicts} conflicto(s) por resolver` });
        if (h.overdue) out.push({ key: "overdue", icon: "fa-clock-o", level: "is-warning", text: `${h.overdue} reserva(s) atrasada(s)` });
        if (h.soft_expiring) out.push({ key: "soft", icon: "fa-hourglass-half", level: "is-warning", text: `${h.soft_expiring} apartado(s) temporal(es) por expirar` });
        if (h.maint_now) out.push({ key: "maint", icon: "fa-wrench", level: "is-info", text: `${h.maint_now} item(s) en mantenimiento` });
        if (h.returns_pending) out.push({ key: "returns", icon: "fa-undo", level: "is-info", text: `${h.returns_pending} retorno(s) pendiente(s) de revisión` });
        return out;
    }
    get hasAlerts() { return this.alerts.length > 0; }

    // ---- KPI cards ----
    get cards() {
        const h = this.state.data.headline;
        return [
            { key: "active", icon: "fa-calendar-check-o", label: "Reservas activas", value: h.active_reservations,
              sub: this.activeSubtitle, sev: "is-info", click: "board",
              tip: "Reservas que bloquean disponibilidad en el periodo seleccionado." },
            { key: "deliv", icon: "fa-truck", label: "Salidas (7 días)", value: h.deliveries_7d,
              sub: "Programadas próximos 7 días", sev: "is-info", click: "deliveries",
              tip: "Equipos con salida programada en los próximos 7 días." },
            { key: "ret", icon: "fa-undo", label: "Retornos (7 días)", value: h.returns_7d,
              sub: "Programados próximos 7 días", sev: "is-info", click: "returns7",
              tip: "Equipos con retorno programado en los próximos 7 días." },
            { key: "items", icon: "fa-barcode", label: "Items gestionados", value: h.total_serials,
              sub: "Seriales rentables planificados", sev: "", click: "board",
              tip: "Total de seriales de productos rentables considerados en la planeación." },
            { key: "conflicts", icon: "fa-exclamation-triangle", label: "Conflictos", value: h.conflicts,
              sub: h.conflicts ? "Requieren revisión inmediata" : "Sin empalmes detectados",
              sev: h.conflicts ? "is-critical" : "is-success", click: "conflicts",
              tip: "Reservas con empalme de la misma serie en periodos que se traslapan." },
            { key: "overdue", icon: "fa-clock-o", label: "Atrasadas", value: h.overdue,
              sub: h.overdue ? "Equipos no devueltos a tiempo" : "Sin atrasos",
              sev: h.overdue ? "is-warning" : "is-success", click: "overdue",
              tip: "Reservas cuyo retorno ya venció y aún no se registra devolución." },
            { key: "soft", icon: "fa-hourglass-half", label: "Apartados por expirar", value: h.soft_expiring,
              sub: h.soft_expiring ? "Confirmar antes de que liberen" : "Sin apartados por expirar",
              sev: h.soft_expiring ? "is-warning" : "", click: "soft",
              tip: "Apartados temporales (soft hold) próximos a expirar automáticamente." },
            { key: "maint", icon: "fa-wrench", label: "En mantenimiento", value: h.maint_now,
              sub: h.damaged_lost ? `${h.damaged_lost} dañados/perdidos` : "Bloqueados por mantenimiento",
              sev: h.maint_now ? "is-warning" : "", click: "maint",
              tip: "Items bloqueados por mantenimiento, limpieza, daño o pérdida." },
            { key: "returns_pending", icon: "fa-inbox", label: "Retornos pendientes", value: h.returns_pending,
              sub: h.returns_pending ? "Por revisar y liberar" : "Sin retornos pendientes",
              sev: h.returns_pending ? "is-warning" : "", click: "returns",
              tip: "Equipos devueltos físicamente que aún no se revisan/liberan." },
        ];
    }

    onCardClick(card) {
        const map = {
            conflicts: () => this.openConflicts(), overdue: () => this.openOverdue(),
            soft: () => this.openSoftHolds(), maint: () => this.openMaintenance(),
            returns: () => this.openReturnsPending(), board: () => this.openBoard(),
            deliveries: () => this.openBoard(), returns7: () => this.openBoard(),
        };
        (map[card.click] || (() => this.openBoard()))();
    }
    onAlertClick(alert) {
        this.onCardClick({ click: alert.key === "soft" ? "soft" : alert.key });
    }

    // ---- clients toggle ----
    setClientBy(c) { this.state.clientBy = c; }
    get clients() {
        const arr = [...this.state.data.top_customers];
        const k = this.state.clientBy;
        arr.sort((a, b) => (b[k] || 0) - (a[k] || 0));
        return arr;
    }
    clientSub(c) {
        if (c.value > 0) return `${this.fmt(c.count)} reservas · ${this.money(c.value)} estimado`;
        return `${this.fmt(c.count)} reservas · ${this.fmt(c.items)} items bloqueados`;
    }

    // ---- maxes ----
    get demandMax() { return Math.max(1, ...this.state.data.demand.map((d) => d.count)); }
    get productsMax() { return Math.max(1, ...this.state.data.top_products.map((p) => p.count)); }
    get clientsMax() { return Math.max(1, ...this.clients.map((c) => c[this.state.clientBy] || 0)); }

    demandTip(d) {
        return `Semana del ${d.label}\n${d.count} items bloqueados\n${d.customers} cliente(s)`;
    }

    // ---- navigation with context ----
    get periodRange() {
        const s = new Date(); const e = new Date(); e.setDate(e.getDate() + this.state.days);
        return { start: isoDay(s), end: isoDay(e) };
    }
    openBoard(extra = {}) {
        const r = this.periodRange;
        this.action.doAction({
            type: "ir.actions.client", tag: "aq_rental_planning_board",
            params: Object.assign({ date_start: r.start, date_end: r.end }, extra),
        });
    }
    openProduct(p) { this.openBoard({ product_id: p.product_id }); }
    openWeek(d) {
        const s = new Date(); s.setDate(s.getDate() + d.week_index * 7);
        const e = new Date(s); e.setDate(e.getDate() + 7);
        this.openBoard({ date_start: isoDay(s), date_end: isoDay(e) });
    }
    _openReservations(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window", name, res_model: "rental.serial.reservation",
            domain, views: [[false, "list"], [false, "form"]],
        });
    }
    openConflicts() { this._openReservations("Conflictos", [["conflict_status", "=", "conflict"]]); }
    openOverdue() {
        this._openReservations("Reservas atrasadas", [
            ["state", "in", ["picked_up", "delivered", "in_use"]],
            ["reservation_block_end", "<", serverNow()],
            ["actual_return_datetime", "=", false]]);
    }
    openSoftHolds() { this._openReservations("Apartados temporales", [["state", "=", "soft_hold"]]); }
    openReturnsPending() { this._openReservations("Retornos pendientes", [["state", "=", "returned"]]); }
    openCustomer(c) { this._openReservations("Reservas · " + c.name, [["partner_id", "=", c.partner_id]]); }
    openMaintenance() {
        this.action.doAction({
            type: "ir.actions.act_window", name: "Mantenimiento / Bloqueos",
            res_model: "rental.serial.downtime",
            domain: [["state", "in", ["scheduled", "in_progress"]]],
            views: [[false, "list"], [false, "form"]],
        });
    }
}

registry.category("actions").add("aq_rental_kpi_dashboard", RentalKpiDashboard);
```

## ./static/src/dashboard/kpi_dashboard.scss
```scss
// ===========================================================================
// AQ Rental — KPI / Planning dashboard (iteration 23)
// Branding: Getting Ready (sage green base + warm neutrals). Alert tints for
// critical metrics. State funnel uses the shared calendar palette (from JS).
// ===========================================================================
$d-green: #8faf9b;
$d-green-dark: #5f7668;
$d-champ: #c9a36a;
$d-taupe: #b8a995;
$d-ink: #1f211d;
$d-muted: #6b7a6f;
$d-faint: #9da9a0;
$d-line: #e3e6dd;
$d-bg: #f7f3ea;
$d-surface: #fffdf8;
$d-track: #e6ebe5;
$d-danger: #b44434;
$d-sh-sm: 0 1px 2px rgba(31, 33, 29, .1);
$d-sh-md: 0 8px 20px rgba(31, 33, 29, .13);

.aq_kpi_dashboard {
    display: flex; flex-direction: column; height: 100%; overflow: hidden;
    background: $d-bg; color: $d-ink; font-size: 13px; -webkit-font-smoothing: antialiased;

    *::-webkit-scrollbar { width: 10px; height: 10px; }
    *::-webkit-scrollbar-thumb { background: #b9c5bb; border-radius: 8px; border: 2px solid transparent; background-clip: content-box; }
    *::-webkit-scrollbar-thumb:hover { background: $d-green; background-clip: content-box; }

    .aq_clickable { cursor: pointer; }

    // ---- topbar
    .aq_kpi_topbar {
        display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
        padding: 14px 22px; background: $d-surface; border-bottom: 1px solid $d-line; box-shadow: $d-sh-sm;
        h1 { font-size: 21px; font-weight: 800; margin: 0; letter-spacing: -.2px; }
        .aq_kpi_sub { font-size: 12px; color: $d-faint; }
        .aq_kpi_controls { display: flex; align-items: center; gap: 8px; }
        .aq_kpi_period {
            background: #e7ece6; border-radius: 10px; padding: 3px; gap: 2px; box-shadow: inset 0 1px 2px rgba(31, 33, 29, .08);
            .btn { border: none !important; border-radius: 7px !important; background: transparent; color: $d-muted; font-weight: 700; box-shadow: none !important; }
            .btn.btn-primary { background: $d-surface; color: $d-green-dark; box-shadow: $d-sh-sm; }
        }
        .btn-secondary { background: $d-green-dark; border-color: $d-green-dark; color: #fffdf8; border-radius: 9px; font-weight: 600;
            &:hover { background: #4e6357; border-color: #4e6357; } }
        .btn-light { border: 1px solid $d-line; border-radius: 9px; background: $d-surface; color: $d-muted; }
    }

    // ---- state screens
    .aq_kpi_state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: $d-faint;
        i { font-size: 40px; opacity: .55; } p { font-size: 15px; margin: 0; } }

    .aq_kpi_scroll { flex: 1; overflow: auto; padding: 16px 22px 26px; }

    // ---- skeletons
    .aq_skeleton { background: linear-gradient(90deg, #eceee9, #f5f6f2, #eceee9); background-size: 200% 100%;
        animation: aqShimmer 1.2s ease-in-out infinite; border: none; min-height: 92px; }
    @keyframes aqShimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

    // ---- alert summary
    .aq_alert_summary { background: #fff7f3; border: 1px solid #f2d9cd; border-radius: 14px; padding: 12px 16px; margin-bottom: 14px; box-shadow: $d-sh-sm; }
    .aq_alert_head { font-weight: 800; font-size: 13px; color: $d-danger; margin-bottom: 8px; i { margin-right: 6px; } }
    .aq_alert_items { display: flex; flex-wrap: wrap; gap: 8px; }
    .aq_alert_chip {
        border: 1px solid transparent; border-radius: 999px; padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer;
        display: inline-flex; align-items: center; gap: 6px; transition: transform .1s;
        &:hover { transform: translateY(-1px); }
        &.is-critical { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
        &.is-warning { background: #fef3c7; color: #92400e; border-color: #fde68a; }
        &.is-info { background: #eef2f0; color: $d-green-dark; border-color: #d8e0da; }
    }
    .aq_alert_ok { display: inline-flex; align-items: center; gap: 8px; color: #15803d; background: #f0fdf4; border: 1px solid #bbf7d0;
        border-radius: 12px; padding: 8px 14px; font-weight: 700; font-size: 12.5px; margin-bottom: 14px; }

    // ---- hero
    .aq_kpi_hero { display: grid; grid-template-columns: 1.5fr 1fr; gap: 16px; margin-bottom: 14px; }
    @media (max-width: 900px) { .aq_kpi_hero { grid-template-columns: 1fr; } }
    .aq_kpi_hero_card { background: $d-surface; border: 1px solid $d-line; border-radius: 18px; box-shadow: $d-sh-sm; padding: 18px 22px; }

    .aq_util { display: flex; align-items: center; gap: 24px;
        &.is-low .aq_util_status { color: #16a34a; } &.is-healthy .aq_util_status { color: $d-green-dark; }
        &.is-high .aq_util_status { color: #b45309; } &.is-saturated .aq_util_status { color: $d-danger; } }
    .aq_kpi_donut {
        width: 124px; height: 124px; border-radius: 50%; flex: 0 0 auto;
        display: flex; align-items: center; justify-content: center; box-shadow: inset 0 0 0 1px rgba(31, 33, 29, .05);
        .aq_kpi_donut_hole { width: 90px; height: 90px; border-radius: 50%; background: $d-surface;
            display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: $d-sh-sm; }
        .aq_donut_val { font-size: 26px; font-weight: 900; letter-spacing: -1px; color: $d-ink; }
        .aq_donut_cap { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: $d-faint; }
    }
    .aq_util_breakdown { display: flex; flex-direction: column; gap: 6px; }
    .aq_util_status { font-size: 15px; font-weight: 800; }
    .aq_util_big { font-size: 14px; color: $d-ink; strong { font-size: 20px; font-weight: 900; } .aq_util_of { color: $d-faint; font-size: 12px; } }
    .aq_util_rows { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 4px; }
    .aq_util_row { display: inline-flex; align-items: center; gap: 6px; color: $d-muted; font-size: 12.5px; }
    .aq_dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block;
        &.is-busy { background: $d-champ; } &.is-ok { background: $d-green; } &.is-muted { background: $d-muted; } }

    .aq_value { display: flex; flex-direction: column; justify-content: center; border: none;
        background: linear-gradient(135deg, #1f211d 0%, #5f7668 55%, #8faf9b 100%); color: #fffdf8; box-shadow: $d-sh-md; }
    .aq_value_icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(255, 253, 248, .16); color: $d-champ;
        display: inline-flex; align-items: center; justify-content: center; font-size: 17px; margin-bottom: 10px; }
    .aq_value_amount { font-size: 30px; font-weight: 900; letter-spacing: -1px; }
    .aq_value_label { font-size: 13px; opacity: .92; margin-top: 2px; }
    .aq_value_sub { font-size: 12px; opacity: .78; margin-top: 6px; }
    .aq_value_delta { display: inline-block; margin-left: 6px; padding: 1px 8px; border-radius: 999px; font-weight: 800; font-size: 11px;
        &.is-up { background: rgba(187, 247, 208, .25); color: #d6f5dd; } &.is-down { background: rgba(254, 202, 202, .25); color: #fed7d7; } }

    // ---- KPI cards
    .aq_kpi_cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .aq_kpi_card {
        display: flex; align-items: center; gap: 13px; background: $d-surface; border: 1px solid $d-line;
        border-radius: 16px; padding: 14px 16px; box-shadow: $d-sh-sm; min-height: 88px; transition: transform .12s, box-shadow .12s;
        &.aq_clickable:hover { transform: translateY(-2px); box-shadow: $d-sh-md; }
        .aq_kpi_card_icon { width: 42px; height: 42px; border-radius: 12px; background: #e6ece5; color: $d-green-dark;
            display: inline-flex; align-items: center; justify-content: center; font-size: 17px; flex: 0 0 auto; }
        .aq_kpi_card_value { font-size: 26px; font-weight: 900; letter-spacing: -.6px; line-height: 1; color: $d-ink; }
        .aq_kpi_card_label { font-size: 12.5px; color: $d-ink; font-weight: 700; margin-top: 3px; }
        .aq_kpi_card_sub { font-size: 11px; color: $d-faint; margin-top: 2px; line-height: 1.25; }

        &.is-info .aq_kpi_card_icon { background: #e2ebe2; color: $d-green-dark; }
        &.is-success { border-color: #cdeccf; .aq_kpi_card_icon { background: #e7f6ea; color: #16a34a; } }
        &.is-warning { border-color: #fde68a; background: #fffdf3; .aq_kpi_card_icon { background: #fef3c7; color: #b45309; } .aq_kpi_card_value { color: #92400e; } }
        &.is-critical { border-color: #fecaca; background: #fff7f6; .aq_kpi_card_icon { background: #fee2e2; color: #dc2626; } .aq_kpi_card_value { color: #b91c1c; } }
    }

    // ---- analytics grid (12 cols)
    .aq_dashboard_grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
    .aq_col_3 { grid-column: span 3; } .aq_col_4 { grid-column: span 4; }
    .aq_col_6 { grid-column: span 6; } .aq_col_12 { grid-column: span 12; }
    @media (max-width: 1200px) { .aq_col_3, .aq_col_4, .aq_col_6 { grid-column: span 6; } }
    @media (max-width: 768px) { .aq_col_3, .aq_col_4, .aq_col_6, .aq_col_12 { grid-column: span 12; } }

    .aq_card { background: $d-surface; border: 1px solid $d-line; border-radius: 18px; box-shadow: $d-sh-sm; }
    .aq_kpi_panel { padding: 16px 18px; }
    .aq_panel_title { font-size: 14px; font-weight: 800; color: $d-ink; margin-bottom: 12px; display: flex; align-items: center; i { color: $d-green-dark; } }
    .aq_panel_caption { font-size: 11.5px; color: $d-faint; margin: -6px 0 12px; }
    .aq_panel_empty { color: $d-faint; padding: 14px 0; text-align: center; }
    .aq_more { margin-top: 10px; font-size: 11.5px; color: $d-green-dark; font-weight: 700; }
    .aq_client_toggle {
        background: #e7ece6; border-radius: 8px; padding: 2px;
        .btn { border: none !important; border-radius: 6px !important; background: transparent; color: $d-muted; font-weight: 700; box-shadow: none !important; font-size: 11px; padding: 2px 9px; }
        .btn.btn-primary { background: $d-surface; color: $d-green-dark; box-shadow: $d-sh-sm; }
    }

    // ---- bars (simple rows)
    .aq_bars { display: flex; flex-direction: column; gap: 9px; }
    .aq_bar_row { display: grid; grid-template-columns: 150px 1fr 78px; align-items: center; gap: 10px; }
    .aq_bar_label { font-size: 12.5px; color: #2f352f; font-weight: 600; white-space: normal; word-break: break-word; line-height: 1.2; }
    .aq_bar_track { height: 11px; background: $d-track; border-radius: 999px; overflow: hidden; }
    .aq_bar_fill { height: 100%; border-radius: 999px; min-width: 4px; transition: width .4s cubic-bezier(.4, 0, .2, 1);
        &.aq_accent { background: linear-gradient(90deg, #8faf9b, #5f7668); }
        &.aq_accent2 { background: linear-gradient(90deg, #d8b98c, #c9a36a); } }
    .aq_bar_value { font-size: 12.5px; font-weight: 800; text-align: right; color: $d-ink; font-variant-numeric: tabular-nums;
        .aq_bar_pct { color: $d-faint; font-weight: 700; font-size: 11px; margin-left: 4px; } }

    // ---- bar blocks (name on top + bar below: products / clients / occupancy)
    .aq_bar_block { display: flex; flex-direction: column; gap: 5px; padding: 7px 9px; border-radius: 10px; transition: background .1s;
        &.aq_clickable:hover { background: #f4f7f3; } }
    .aq_bar_block_head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
    .aq_bar_block_name { font-size: 13px; font-weight: 700; color: $d-ink; word-break: break-word; }
    .aq_bar_block_meta { font-size: 11.5px; color: $d-muted; white-space: nowrap; flex: 0 0 auto; }

    .aq_product_occupancy {
        &.is-normal .aq_bar_fill { background: #6f8f7c; }
        &.is-warning .aq_bar_fill { background: #d6a85f; }
        &.is-high .aq_bar_fill { background: #c46f4f; }
        &.is-full { .aq_bar_fill { background: #b44434; } .aq_bar_block_name::after { content: " · SATURADO"; color: #b44434; font-size: 10px; font-weight: 800; } }
    }

    // ---- column chart
    .aq_columns { display: flex; align-items: flex-end; gap: 8px; height: 160px; }
    .aq_col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; border-radius: 8px;
        &.aq_clickable:hover { background: #f4f7f3; } }
    .aq_col_val { font-size: 12px; font-weight: 800; color: $d-muted; margin-bottom: 4px; }
    .aq_col_bar_wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
    .aq_col_bar { width: 60%; min-height: 4px; border-radius: 8px 8px 3px 3px; transition: height .4s cubic-bezier(.4, 0, .2, 1);
        box-shadow: inset 0 1px 0 rgba(255, 253, 248, .3);
        &.lvl-low { background: linear-gradient(180deg, #a9c2b2, #6f8f7c); }
        &.lvl-mid { background: linear-gradient(180deg, #e0c389, #d6a85f); }
        &.lvl-high { background: linear-gradient(180deg, #d68f6e, #c46f4f); } }
    .aq_col_label { font-size: 10px; color: $d-faint; margin: 6px 2px 0; font-weight: 600; white-space: nowrap; }
}
```

## ./static/src/dashboard/kpi_dashboard.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="aq_rental_serial_planning.KpiDashboard">
        <div class="aq_kpi_dashboard">

            <!-- Header -->
            <div class="aq_kpi_topbar">
                <div class="aq_kpi_titles">
                    <h1>Indicadores de Planeación</h1>
                    <span class="aq_kpi_sub">
                        <t t-if="ready"><t t-esc="periodLabel"/> · actualizado <t t-esc="state.data.generated"/></t>
                        <t t-else="">Centro de control operativo</t>
                    </span>
                </div>
                <div class="aq_kpi_controls">
                    <div class="btn-group aq_kpi_period">
                        <button class="btn btn-sm" t-att-class="state.days === 30 ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setDays(30)">30 d</button>
                        <button class="btn btn-sm" t-att-class="state.days === 60 ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setDays(60)">60 d</button>
                        <button class="btn btn-sm" t-att-class="state.days === 90 ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setDays(90)">90 d</button>
                    </div>
                    <button class="btn btn-light btn-sm" t-on-click="() => this.refresh()" title="Actualizar"><i class="fa fa-refresh"/></button>
                    <button class="btn btn-secondary btn-sm" t-on-click="() => this.openBoard()"><i class="fa fa-calendar me-1"/> Abrir tablero</button>
                </div>
            </div>

            <!-- Loading skeleton -->
            <div t-if="state.loading" class="aq_kpi_scroll">
                <div class="aq_kpi_cards">
                    <t t-foreach="[1,2,3,4,5,6,7,8]" t-as="n" t-key="n"><div class="aq_kpi_card aq_skeleton"/></t>
                </div>
                <div class="aq_dashboard_grid">
                    <div class="aq_card aq_skeleton aq_col_6" style="height:220px"/>
                    <div class="aq_card aq_skeleton aq_col_6" style="height:220px"/>
                </div>
            </div>

            <!-- Error -->
            <div t-elif="state.error" class="aq_kpi_state">
                <i class="fa fa-exclamation-circle"/>
                <p>No se pudieron cargar los indicadores.</p>
                <button class="btn btn-secondary btn-sm" t-on-click="() => this.refresh()">Intentar de nuevo</button>
            </div>

            <!-- Empty -->
            <div t-elif="!state.data.headline.total_serials" class="aq_kpi_state">
                <i class="fa fa-inbox"/>
                <p>No hay items rentables planificados para este periodo.</p>
            </div>

            <!-- Content -->
            <div t-else="" class="aq_kpi_scroll">

                <!-- Atención requerida -->
                <div t-if="hasAlerts" class="aq_alert_summary">
                    <div class="aq_alert_head"><i class="fa fa-bell"/> Atención requerida</div>
                    <div class="aq_alert_items">
                        <t t-foreach="alerts" t-as="a" t-key="a.key">
                            <button class="aq_alert_chip" t-att-class="a.level" t-on-click="() => this.onAlertClick(a)">
                                <i t-attf-class="fa {{a.icon}}"/> <t t-esc="a.text"/>
                            </button>
                        </t>
                    </div>
                </div>
                <div t-else="" class="aq_alert_ok"><i class="fa fa-check-circle"/> Sin incidencias críticas</div>

                <!-- Hero -->
                <div class="aq_kpi_hero">
                    <div class="aq_kpi_hero_card aq_util" t-att-class="utilStatus.cls">
                        <div class="aq_kpi_donut" t-att-style="donutStyle">
                            <div class="aq_kpi_donut_hole">
                                <span class="aq_donut_val"><t t-esc="state.data.headline.utilization"/>%</span>
                                <span class="aq_donut_cap">Utilización</span>
                            </div>
                        </div>
                        <div class="aq_util_breakdown">
                            <div class="aq_util_status" t-esc="utilStatus.label"/>
                            <div class="aq_util_big"><strong t-esc="fmt(state.data.headline.available_now)"/> disponibles <span class="aq_util_of">de <t t-esc="fmt(state.data.headline.total_serials)"/> items</span></div>
                            <div class="aq_util_rows">
                                <span class="aq_util_row"><span class="aq_dot is-busy"/><t t-esc="fmt(state.data.headline.blocked_now)"/> ocupados</span>
                                <span class="aq_util_row"><span class="aq_dot is-muted"/><t t-esc="fmt(state.data.headline.maint_now)"/> en mantenimiento</span>
                            </div>
                        </div>
                    </div>

                    <div class="aq_kpi_hero_card aq_value" t-att-title="'Valor estimado de pedidos de evento activos en los próximos ' + state.days + ' días'">
                        <div class="aq_value_icon"><i class="fa fa-star"/></div>
                        <div class="aq_value_amount" t-esc="money(state.data.headline.events_value)"/>
                        <div class="aq_value_label">Valor estimado próximos <t t-esc="state.days"/> días</div>
                        <div class="aq_value_sub">
                            <t t-esc="state.data.headline.upcoming_events"/> eventos activos
                            <span t-if="state.data.headline.events_delta !== null" class="aq_value_delta"
                                  t-att-class="state.data.headline.events_delta >= 0 ? 'is-up' : 'is-down'">
                                <t t-esc="state.data.headline.events_delta >= 0 ? '+' : ''"/><t t-esc="state.data.headline.events_delta"/>% vs periodo anterior
                            </span>
                        </div>
                    </div>
                </div>

                <!-- KPI cards -->
                <div class="aq_kpi_cards">
                    <t t-foreach="cards" t-as="c" t-key="c.key">
                        <div class="aq_kpi_card aq_clickable" t-att-class="c.sev" t-att-title="c.tip" t-on-click="() => this.onCardClick(c)">
                            <div class="aq_kpi_card_icon"><i t-attf-class="fa {{c.icon}}"/></div>
                            <div class="aq_kpi_card_body">
                                <div class="aq_kpi_card_value" t-esc="fmt(c.value)"/>
                                <div class="aq_kpi_card_label" t-esc="c.label"/>
                                <div class="aq_kpi_card_sub" t-esc="c.sub"/>
                            </div>
                        </div>
                    </t>
                </div>

                <!-- Analytics grid -->
                <div class="aq_dashboard_grid">
                    <!-- estado -->
                    <div class="aq_card aq_col_6 aq_kpi_panel">
                        <div class="aq_panel_title"><i class="fa fa-bars me-2"/>Reservas por estado</div>
                        <div t-if="!state.data.reservations_by_state.length" class="aq_panel_empty">Sin reservas en el periodo.</div>
                        <div class="aq_bars">
                            <t t-foreach="state.data.reservations_by_state" t-as="s" t-key="s.key">
                                <div class="aq_bar_row" t-attf-title="{{s.label}}: {{s.count}} reservas · {{s.pct}}% del total">
                                    <div class="aq_bar_label" t-esc="s.label"/>
                                    <div class="aq_bar_track">
                                        <div class="aq_bar_fill" t-attf-style="width:{{s.pct}}%;background:{{stateColor(s.key)}};"/>
                                    </div>
                                    <div class="aq_bar_value"><t t-esc="s.count"/> <span class="aq_bar_pct"><t t-esc="s.pct"/>%</span></div>
                                </div>
                            </t>
                        </div>
                    </div>

                    <!-- demanda -->
                    <div class="aq_card aq_col_6 aq_kpi_panel">
                        <div class="aq_panel_title"><i class="fa fa-line-chart me-2"/>Demanda próximas 8 semanas</div>
                        <div class="aq_panel_caption">Items bloqueados por semana (% del inventario)</div>
                        <div class="aq_columns">
                            <t t-foreach="state.data.demand" t-as="d" t-key="d.label">
                                <div class="aq_col aq_clickable" t-att-title="demandTip(d)" t-on-click="() => this.openWeek(d)">
                                    <div class="aq_col_val" t-esc="d.count"/>
                                    <div class="aq_col_bar_wrap">
                                        <div t-attf-class="aq_col_bar lvl-{{d.level}}" t-attf-style="height:{{pct(d.count, demandMax)}}%;"/>
                                    </div>
                                    <div class="aq_col_label" t-esc="d.label"/>
                                </div>
                            </t>
                        </div>
                    </div>

                    <!-- productos -->
                    <div class="aq_card aq_col_6 aq_kpi_panel">
                        <div class="aq_panel_title"><i class="fa fa-cube me-2"/>Productos más solicitados</div>
                        <div t-if="!state.data.top_products.length" class="aq_panel_empty">Sin datos en el periodo.</div>
                        <div class="aq_bars">
                            <t t-foreach="state.data.top_products" t-as="p" t-key="p.name">
                                <div class="aq_bar_block aq_clickable" t-on-click="() => this.openProduct(p)">
                                    <div class="aq_bar_block_head">
                                        <span class="aq_bar_block_name" t-esc="p.name"/>
                                        <span class="aq_bar_block_meta"><t t-esc="p.count"/> items · <t t-esc="p.orders"/> evento(s)</span>
                                    </div>
                                    <div class="aq_bar_track">
                                        <div class="aq_bar_fill aq_accent" t-attf-style="width:{{pct(p.count, productsMax)}}%;"/>
                                    </div>
                                </div>
                            </t>
                        </div>
                        <div t-if="state.data.products_more" class="aq_more">+ <t t-esc="state.data.products_more"/> productos más</div>
                    </div>

                    <!-- ocupación -->
                    <div class="aq_card aq_col_6 aq_kpi_panel">
                        <div class="aq_panel_title"><i class="fa fa-tachometer me-2"/>Ocupación por producto (ahora)</div>
                        <div t-if="!state.data.util_by_product.length" class="aq_panel_empty">Sin items gestionados.</div>
                        <div class="aq_bars">
                            <t t-foreach="state.data.util_by_product" t-as="p" t-key="p.name">
                                <div class="aq_bar_block aq_product_occupancy aq_clickable" t-att-class="occLevel(p.pct)" t-on-click="() => this.openProduct(p)">
                                    <div class="aq_bar_block_head">
                                        <span class="aq_bar_block_name" t-esc="p.name"/>
                                        <span class="aq_bar_block_meta"><t t-esc="p.pct"/>% ocupado · <t t-esc="p.available"/> disp. de <t t-esc="p.total"/></span>
                                    </div>
                                    <div class="aq_bar_track">
                                        <div class="aq_bar_fill" t-attf-style="width:{{p.pct}}%;"/>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>

                    <!-- clientes -->
                    <div class="aq_card aq_col_12 aq_kpi_panel">
                        <div class="aq_panel_title">
                            <i class="fa fa-users me-2"/>Clientes con más reservas
                            <div class="btn-group aq_client_toggle ms-auto">
                                <button class="btn btn-sm" t-att-class="state.clientBy === 'count' ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setClientBy('count')">Reservas</button>
                                <button class="btn btn-sm" t-att-class="state.clientBy === 'items' ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setClientBy('items')">Items</button>
                                <button class="btn btn-sm" t-att-class="state.clientBy === 'value' ? 'btn-primary' : 'btn-light'" t-on-click="() => this.setClientBy('value')">Valor</button>
                            </div>
                        </div>
                        <div t-if="!clients.length" class="aq_panel_empty">Sin clientes con reservas.</div>
                        <div class="aq_bars">
                            <t t-foreach="clients" t-as="c" t-key="c.partner_id">
                                <div class="aq_bar_block aq_clickable" t-on-click="() => this.openCustomer(c)">
                                    <div class="aq_bar_block_head">
                                        <span class="aq_bar_block_name" t-esc="c.name"/>
                                        <span class="aq_bar_block_meta" t-esc="clientSub(c)"/>
                                    </div>
                                    <div class="aq_bar_track">
                                        <div class="aq_bar_fill aq_accent2" t-attf-style="width:{{pct(c[state.clientBy], clientsMax)}}%;"/>
                                    </div>
                                </div>
                            </t>
                        </div>
                        <div t-if="state.data.customers_more" class="aq_more">+ <t t-esc="state.data.customers_more"/> clientes más</div>
                    </div>
                </div>
            </div>
        </div>
    </t>
</templates>
```

## ./static/src/planning/planning_board.js
```js
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";

// --- Humanized states (never show technical values to the user) ---
const RENTAL_STATE_LABELS = {
    draft: "Borrador",
    quotation: "Cotización",
    soft_hold: "Apartado temporal",
    reserved: "Reservado",
    prepared: "Preparado",
    picked_up: "Retirado",
    delivered: "Entregado",
    in_use: "En uso",
    returned: "Devuelto por revisar",
    released: "Liberado",
    cancelled: "Cancelado",
    maintenance: "Mantenimiento / Bloqueo",
    conflict: "Conflicto",
};

const STATE_OPERATIONAL_HINT = {
    reserved: "Reservado (serie bloqueada)",
    prepared: "Preparado en almacén",
    picked_up: "Retirado del almacén",
    delivered: "Entregado / instalado",
    in_use: "En uso durante el evento",
    returned: "Devuelto, pendiente de revisión",
    released: "Liberado y disponible",
    soft_hold: "Apartado temporal",
};

const REASON_LABELS = {
    maintenance: "Mantenimiento",
    cleaning: "Limpieza",
    repair: "Reparación",
    damaged: "Dañado",
    lost: "Perdido",
    internal_use: "Uso interno",
    other: "Otro",
};

// Hex mirror of the SCSS palette (used for legend swatches only).
const STATE_COLORS = {
    draft: "#cbd5e1", quotation: "#94a3b8", soft_hold: "#f59e0b",
    reserved: "#38bdf8", prepared: "#7c3aed", picked_up: "#2563eb",
    delivered: "#10b981", in_use: "#15803d", returned: "#f97316",
    released: "#d1d5db", maintenance: "#4b5563", conflict: "#dc2626",
};

const LEGEND_GROUPS = [
    { title: "Comercial", states: ["draft", "quotation", "soft_hold"] },
    { title: "Operación", states: ["reserved", "prepared", "picked_up", "delivered", "in_use"] },
    { title: "Cierre", states: ["returned", "released"] },
    { title: "Incidencias", states: ["maintenance", "conflict"] },
];

// Severity for picking a representative state on a serial row.
const STATE_PRIORITY = {
    in_use: 7, delivered: 6, picked_up: 5, prepared: 4,
    reserved: 3, returned: 2, soft_hold: 1,
};
const OPERATION_STATES = ["reserved", "prepared", "picked_up", "delivered", "in_use", "returned"];

const WD = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MO_FULL = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const VIEW_MODES = [
    { key: "timeline", label: "Timeline", icon: "fa-tasks" },
    { key: "month", label: "Mes", icon: "fa-calendar" },
    { key: "agenda", label: "Agenda", icon: "fa-list-ul" },
    { key: "heatmap", label: "Carga", icon: "fa-th" },
    { key: "customer", label: "Cliente", icon: "fa-users" },
];

// ---------- date helpers (UTC-naive in, browser-local out) ----------
function pad(n) { return String(n).padStart(2, "0"); }
function parseUTC(s) {
    if (!s) return null;
    const hasTZ = /[zZ]$|[+-]\d\d:?\d\d$/.test(s);
    return new Date(hasTZ ? s : s.replace(" ", "T") + "Z");
}
function toServer(d) { return d.toISOString().slice(0, 19).replace("T", " "); }
function isoDate(d) { return d.toISOString().slice(0, 10); }
function dayStartUTC(s) { return new Date(s + "T00:00:00Z"); }
function dayEndUTC(s) { return new Date(s + "T23:59:59Z"); }
function addDaysUTC(d, n) { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x; }
function addMonthsUTC(d, n) { const x = new Date(d); x.setUTCMonth(x.getUTCMonth() + n); return x; }

function formatRentalDateTime(dt) {
    if (!dt) return "";
    return `${WD[dt.getDay()]} ${dt.getDate()} ${MO[dt.getMonth()]}, ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}
function formatRentalDate(dt) {
    if (!dt) return "";
    return `${WD[dt.getDay()]} ${dt.getDate()} ${MO[dt.getMonth()]}`;
}
function formatRentalDateRange(a, b) {
    return `${formatRentalDateTime(a)} → ${formatRentalDateTime(b)}`;
}
const AVATAR_COLORS = ["#0E7C86", "#7c3aed", "#2563eb", "#db2777", "#ea580c",
                       "#0891b2", "#65a30d", "#9333ea", "#dc2626", "#0d9488"];
function avatarInitials(name) {
    const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}
function avatarColor(name) {
    let h = 0;
    for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function getRentalDurationLabel(a, b) {
    let ms = b - a;
    if (ms < 0) ms = 0;
    const days = Math.floor(ms / 86400000);
    const hours = Math.round((ms % 86400000) / 3600000);
    const parts = [];
    if (days) parts.push(days + (days === 1 ? " día" : " días"));
    if (hours) parts.push(hours + " h");
    return parts.length ? parts.join(" ") : "0 h";
}

export class RentalPlanningBoard extends Component {
    static template = "aq_rental_serial_planning.PlanningBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.labels = RENTAL_STATE_LABELS;

        const params = (this.props.action && this.props.action.params) || {};
        const today = isoDate(new Date());
        let density = "comfortable";
        try { density = window.localStorage.getItem("aq_rental_density") || "comfortable"; } catch (e) { /* ignore */ }

        this.state = useState({
            loading: true,
            viewMode: params.view_mode || "timeline",
            monthProductId: null,
            zoom: "week",
            dateStart: params.date_start || today,
            dateEnd: params.date_end || isoDate(addDaysUTC(new Date(), 14)),
            products: [],
            expanded: {},
            density,
            legendCollapsed: false,
            search: "",
            filters: {
                warehouse_id: params.warehouse_id || null,
                product_ids: params.product_id ? [params.product_id] : null,
                package_id: params.package_id || null,
                partner_id: params.partner_id || null,
                states: params.states || null,
            },
            meta: { warehouses: [], products: [], packages: [], states: [] },
            selected: null,
            tooltip: null,
            showDowntime: false,
            downtimeForm: { lot_id: null, reason: "maintenance", start: "", end: "" },
        });

        this._onKeydown = (ev) => {
            if (ev.key === "Escape") {
                if (this.state.tooltip) this.state.tooltip = null;
                else if (this.state.showDowntime) this.state.showDowntime = false;
                else if (this.state.selected) this.state.selected = null;
            }
        };

        onWillStart(async () => {
            this.state.meta = await this.orm.call(
                "rental.serial.reservation", "board_filters", []);
            await this.loadBoard();
        });
        onMounted(() => document.addEventListener("keydown", this._onKeydown));
        onWillUnmount(() => document.removeEventListener("keydown", this._onKeydown));
    }

    // ------------------------------------------------------------------
    // Data + decoration (compute everything once per load = memoization)
    // ------------------------------------------------------------------
    async loadBoard() {
        this.state.loading = true;
        const f = this.state.filters;
        const data = await this.orm.call(
            "rental.serial.reservation", "serial_timeline", [], {
                date_start: toServer(this.rangeStart),
                date_end: toServer(this.rangeEnd),
                product_ids: f.product_ids,
                warehouse_id: f.warehouse_id,
                package_id: f.package_id,
                partner_id: f.partner_id,
                states: f.states,
            });
        this._decorate(data.products);
        this.state.products = data.products;
        for (const p of data.products) {
            if (!(p.product_id in this.state.expanded)) {
                this.state.expanded[p.product_id] = data.products.length <= 4;
            }
        }
        this.state.loading = false;
    }

    _decorate(products) {
        const rs = this.rangeStart.getTime();
        const span = this.spanMs;
        for (const product of products) {
            for (const serial of product.serials) {
                // sort blocks by start for conflict pairing
                serial.blocks.sort((a, b) => parseUTC(a.start) - parseUTC(b.start));
                for (let i = 0; i < serial.blocks.length; i++) {
                    const block = serial.blocks[i];
                    const s = parseUTC(block.start), e = parseUTC(block.end);
                    const sMs = Math.max(s.getTime(), rs);
                    const eMs = Math.min(e.getTime(), this.rangeEnd.getTime());
                    const leftPct = ((sMs - rs) / span) * 100;
                    const widthPct = Math.max(((eMs - sMs) / span) * 100, 0.5);
                    block._leftPct = leftPct;
                    block._widthPct = widthPct;
                    block._style = `left:${leftPct}%;width:${widthPct}%;`;
                    block._sizeClass = widthPct < 6 ? "is-compact"
                        : widthPct < 16 ? "is-medium" : "is-wide";
                    block._isDowntime = block.type === "downtime";
                    block._stateKey = block._isDowntime ? "maintenance" : block.state;
                    block._stateClass = `aq_state_${block._stateKey}`;
                    block._stateLabel = RENTAL_STATE_LABELS[block._stateKey] || block._stateKey;
                    block._opLabel = STATE_OPERATIONAL_HINT[block.state] || block._stateLabel;
                    block._reasonLabel = block.reason ? (REASON_LABELS[block.reason] || block.reason) : "";
                    // human dates
                    block._startLabel = formatRentalDateTime(s);
                    block._endLabel = formatRentalDateTime(e);
                    block._rangeLabel = formatRentalDateRange(s, e);
                    block._durationLabel = getRentalDurationLabel(s, e);
                    // billable inner segment (relative to the block)
                    const bs = parseUTC(block.billable_start), be = parseUTC(block.billable_end);
                    if (bs && be && e > s) {
                        const total = e.getTime() - s.getTime();
                        const segL = Math.max(((bs.getTime() - s.getTime()) / total) * 100, 0);
                        const segR = Math.min(((be.getTime() - s.getTime()) / total) * 100, 100);
                        block._billableStyle = `left:${segL}%;width:${Math.max(segR - segL, 1)}%;`;
                        block._billableLabel = bs.toDateString() === be.toDateString()
                            ? `${formatRentalDate(bs)}, ${pad(bs.getHours())}:${pad(bs.getMinutes())}–${pad(be.getHours())}:${pad(be.getMinutes())}`
                            : formatRentalDateRange(bs, be);
                    } else {
                        block._billableStyle = null;
                        block._billableLabel = "";
                    }
                    // precomputed booleans (avoid `and` in OWL templates)
                    block._overdueOnly = !!block.overdue && !block.conflict;
                    block._hasSaleOrder = !block._isDowntime && !!block.sale_order_id;
                    block._blocking = block._isDowntime
                        || OPERATION_STATES.includes(block.state)
                        || block.state === "soft_hold";
                    // conflict partner (overlap with a sibling on the same serial)
                    block._conflictWith = "";
                    if (block.conflict) {
                        for (let j = 0; j < serial.blocks.length; j++) {
                            if (j === i) continue;
                            const o = serial.blocks[j];
                            if (parseUTC(o.start) < e && parseUTC(o.end) > s) {
                                block._conflictWith = o.name;
                                break;
                            }
                        }
                    }
                }
                this._classifySerial(serial);
            }
            this._summarizeProduct(product);
        }
    }

    _classifySerial(serial) {
        const blocking = serial.blocks.filter(
            (b) => b._isDowntime || OPERATION_STATES.includes(b.state) || b.state === "soft_hold");
        serial._isBlocked = blocking.length > 0;
        serial._hasConflict = serial.blocks.some((b) => b.conflict);
        serial._hasMaint = serial.blocks.some((b) => b._isDowntime);
        serial._hasOverdue = serial.blocks.some((b) => b.overdue);
        let rep = "available";
        if (serial._hasConflict) rep = "conflict";
        else if (serial._hasMaint) rep = "maintenance";
        else {
            let best = -1;
            for (const b of blocking) {
                const p = STATE_PRIORITY[b.state] || 0;
                if (p > best) { best = p; rep = b.state; }
            }
        }
        serial._badgeState = rep;
        serial._badgeLabel = RENTAL_STATE_LABELS[rep] || "Disponible";
        serial._badgeClass = `aq_serial_badge aq_state_${rep}`;
    }

    _summarizeProduct(product) {
        const total = product.serials.length;
        const blocked = product.serials.filter((s) => s._isBlocked).length;
        const available = total - blocked;
        let badge = "is-ok";
        if (available === 0) badge = "is-full";
        else if (blocked > 0) badge = "is-warning";
        product._summary = { total, blocked, available, badge };
    }

    // ------------------------------------------------------------------
    // Derived view data
    // ------------------------------------------------------------------
    get searching() { return this.state.search.trim().length > 0; }

    get filteredProducts() {
        const q = this.state.search.trim().toLowerCase();
        if (!q) return this.state.products;
        const out = [];
        for (const p of this.state.products) {
            const pMatch = (p.product_name || "").toLowerCase().includes(q)
                || (p.sku || "").toLowerCase().includes(q);
            if (pMatch) { out.push(p); continue; }
            const serials = p.serials.filter((s) =>
                (s.lot_name || "").toLowerCase().includes(q)
                || s.blocks.some((b) => (b.partner || "").toLowerCase().includes(q)
                    || (b.name || "").toLowerCase().includes(q)));
            if (serials.length) out.push(Object.assign({}, p, { serials }));
        }
        return out;
    }

    isExpanded(product) {
        return this.searching || !!this.state.expanded[product.product_id];
    }

    get kpis() {
        let visible = 0, available = 0, occupied = 0, soft = 0, conflict = 0, maint = 0;
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                visible++;
                if (s._hasConflict) conflict++;
                else if (s._hasMaint) maint++;
                else if (s._badgeState === "soft_hold") soft++;
                else if (s._isBlocked) occupied++;
                else available++;
            }
        }
        return [
            { key: "visible", label: "Items visibles", value: visible, cls: "", icon: "fa-barcode" },
            { key: "available", label: "Disponibles", value: available, cls: "is-ok", icon: "fa-check-circle" },
            { key: "occupied", label: "Ocupados", value: occupied, cls: "is-busy", icon: "fa-cube" },
            { key: "soft", label: "Apartados", value: soft, cls: "is-warn", icon: "fa-hourglass-half" },
            { key: "conflict", label: "Conflictos", value: conflict, cls: conflict ? "is-danger" : "", icon: "fa-exclamation-triangle" },
            { key: "maint", label: "Mantenimiento", value: maint, cls: maint ? "is-muted" : "", icon: "fa-wrench" },
        ];
    }

    get activeFilterChips() {
        const chips = [];
        const f = this.state.filters;
        const wh = this.state.meta.warehouses.find((w) => w.id === f.warehouse_id);
        chips.push({ key: "wh", label: "Almacén", value: wh ? wh.name : "Todos", active: !!wh });
        const pkg = this.state.meta.packages.find((p) => p.id === f.package_id);
        chips.push({ key: "pkg", label: "Paquete", value: pkg ? pkg.name : "Todos", active: !!pkg });
        const st = f.states && f.states.length
            ? (this.state.meta.states.find((s) => s.key === f.states[0]) || {}).label
            : null;
        chips.push({ key: "st", label: "Estado", value: st || "Todos", active: !!st });
        return chips;
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return !!(f.warehouse_id || f.package_id || (f.states && f.states.length) || f.partner_id);
    }

    get legendGroups() {
        return LEGEND_GROUPS.map((g) => ({
            title: g.title,
            items: g.states.map((s) => ({
                key: s, label: RENTAL_STATE_LABELS[s], color: STATE_COLORS[s],
                cls: `aq_state_${s}`,
            })),
        }));
    }

    // ------------------------------------------------------------------
    // Time axis
    // ------------------------------------------------------------------
    get rangeStart() { return dayStartUTC(this.state.dateStart); }
    get rangeEnd() { return dayEndUTC(this.state.dateEnd); }
    get spanMs() { return Math.max(this.rangeEnd.getTime() - this.rangeStart.getTime(), 1); }

    get columns() {
        const cols = [];
        const todayISO = isoDate(new Date());
        let cursor = this.rangeStart;
        const endMs = this.rangeEnd.getTime();
        let guard = 0;
        while (cursor.getTime() < endMs && guard < 400) {
            const dow = cursor.getUTCDay();
            const key = isoDate(cursor);
            cols.push({
                key,
                label: this.state.zoom === "month"
                    ? `${MO[cursor.getUTCMonth()]} ${cursor.getUTCFullYear()}`
                    : `${WD[dow]} ${pad(cursor.getUTCDate())}`,
                left: ((cursor.getTime() - this.rangeStart.getTime()) / this.spanMs) * 100,
                isWeekend: dow === 0 || dow === 6,
                isToday: key === todayISO,
            });
            cursor = this.state.zoom === "month" ? addMonthsUTC(cursor, 1) : addDaysUTC(cursor, 1);
            guard++;
        }
        return cols;
    }

    get todayLineLeft() {
        const now = Date.now();
        if (now < this.rangeStart.getTime() || now > this.rangeEnd.getTime()) return null;
        return ((now - this.rangeStart.getTime()) / this.spanMs) * 100;
    }

    get densityClass() {
        return this.state.density === "compact"
            ? "is-density-compact" : "is-density-comfortable";
    }

    blockClass(block) {
        let c = `aq_reservation_block ${block._stateClass} ${block._sizeClass}`;
        if (block._isDowntime) c += " aq_is_downtime";
        if (block.conflict) c += " has-conflict";
        if (block.overdue) c += " is-overdue";
        return c;
    }

    // ==================================================================
    // Alternate view modes (all derived from the already-loaded data)
    // ==================================================================
    get viewModes() { return VIEW_MODES; }
    get showStateLegend() { return ["timeline", "customer"].includes(this.state.viewMode); }
    get showZoom() { return this.state.viewMode !== "month"; }
    get isTimelineLike() { return ["timeline", "customer", "heatmap", "agenda"].includes(this.state.viewMode); }

    setViewMode(mode) {
        this.state.viewMode = mode;
        if (mode === "month") {
            const d = dayStartUTC(this.state.dateStart);
            const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
            const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
            this.state.dateStart = isoDate(first);
            this.state.dateEnd = isoDate(last);
            if (!this.state.monthProductId && this.state.products.length) {
                this.state.monthProductId = this.state.products[0].product_id;
            }
            this.loadBoard();
        }
    }
    nav(dir) {
        if (this.state.viewMode === "month") this.monthShift(dir);
        else this.shift(dir);
    }
    monthShift(dir) {
        const d = dayStartUTC(this.state.dateStart);
        const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + dir, 1));
        const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + dir + 1, 0));
        this.state.dateStart = isoDate(first);
        this.state.dateEnd = isoDate(last);
        this.loadBoard();
    }
    onMonthProductChange(ev) { this.state.monthProductId = parseInt(ev.target.value); }

    // --- shared day axis ---
    get rangeDays() {
        const out = [];
        let cur = this.rangeStart;
        const end = this.rangeEnd.getTime();
        const todayISO = isoDate(new Date());
        let guard = 0;
        while (cur.getTime() < end && guard < 92) {
            const dow = cur.getUTCDay();
            const key = isoDate(cur);
            out.push({
                key, ms: cur.getTime(),
                label: `${WD[dow]} ${pad(cur.getUTCDate())}`,
                full: `${WD[dow]} ${cur.getUTCDate()} ${MO[cur.getUTCMonth()]}`,
                isWeekend: dow === 0 || dow === 6,
                isToday: key === todayISO,
            });
            cur = addDaysUTC(cur, 1);
            guard++;
        }
        return out;
    }

    _dayBusy(product, ds, de) {
        let busy = 0;
        for (const s of product.serials) {
            for (const b of s.blocks) {
                if (b._blocking
                    && parseUTC(b.start).getTime() < de
                    && parseUTC(b.end).getTime() > ds) { busy++; break; }
            }
        }
        return busy;
    }
    _level(busy, total) {
        if (!total) return "none";
        const r = busy / total;
        if (r >= 1) return "full";
        if (r >= 0.66) return "high";
        if (r >= 0.33) return "mid";
        if (r > 0) return "low";
        return "free";
    }

    // --- month (availability calendar for one product) ---
    get monthProducts() { return this.state.products; }
    get monthProduct() {
        return this.state.products.find((p) => p.product_id === this.state.monthProductId)
            || this.state.products[0] || null;
    }
    get monthLabel() {
        const d = dayStartUTC(this.state.dateStart);
        return `${MO_FULL[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    }
    get monthWeeks() {
        const product = this.monthProduct;
        const d = dayStartUTC(this.state.dateStart);
        const year = d.getUTCFullYear(), month = d.getUTCMonth();
        const startDow = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7; // Monday=0
        const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
        const todayISO = isoDate(new Date());
        const cells = [];
        for (let i = 0; i < startDow; i++) cells.push(null);
        for (let day = 1; day <= daysInMonth; day++) {
            const ds = Date.UTC(year, month, day);
            const total = product ? product.serials.length : 0;
            const busy = product ? this._dayBusy(product, ds, ds + 86400000) : 0;
            const dow = new Date(ds).getUTCDay();
            const level = this._level(busy, total);
            const isToday = isoDate(new Date(ds)) === todayISO;
            const isWeekend = dow === 0 || dow === 6;
            cells.push({
                key: `${year}-${month}-${day}`, day,
                total, busy, free: total - busy, level, isToday, isWeekend,
                pct: total ? Math.round((busy / total) * 100) : 0,
                cls: `aq_month_cell lvl-${level}`
                    + (isToday ? " is-today" : "")
                    + (isWeekend ? " is-weekend" : ""),
            });
        }
        while (cells.length % 7) cells.push(null);
        const weeks = [];
        for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
        return weeks;
    }
    monthDayDrill() {
        const p = this.monthProduct;
        if (p) this.state.filters.product_ids = [p.product_id];
        this.state.viewMode = "timeline";
        this.loadBoard();
    }

    // --- heatmap (products x days, occupation level) ---
    get heatmapRows() {
        const days = this.rangeDays;
        return this.filteredProducts.map((p) => ({
            product: p,
            total: p.serials.length,
            cells: days.map((day) => {
                const total = p.serials.length;
                const busy = this._dayBusy(p, day.ms, day.ms + 86400000);
                return { key: day.key, busy, total, free: total - busy, level: this._level(busy, total) };
            }),
        }));
    }
    heatDrill(product) {
        this.state.filters.product_ids = [product.product_id];
        this.state.viewMode = "timeline";
        this.loadBoard();
    }

    // --- agenda (operational day list) ---
    _agendaItem(g) {
        return {
            label: `${g.count}× ${g.product}`,
            partner: g.partner, order: g.order,
            stateLabel: RENTAL_STATE_LABELS[g.state] || g.state,
            rep: g.rep,
        };
    }
    get agendaDays() {
        const inRange = new Set(this.rangeDays.map((d) => d.key));
        const buckets = {};
        const ensure = (k) => buckets[k] || (buckets[k] = { salidas: {}, retornos: {} });
        const push = (side, gkey, b) => {
            side[gkey] || (side[gkey] = {
                count: 0, product: b.product_name, partner: b.partner,
                order: b.sale_order, state: b.state, rep: b.id,
            });
            side[gkey].count++;
        };
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                for (const b of s.blocks) {
                    if (b._isDowntime) continue;
                    const gkey = (b.sale_order || b.partner || "—") + "|" + (b.product_name || "");
                    const startKey = isoDate(parseUTC(b.start));
                    const endKey = isoDate(parseUTC(b.end));
                    if (inRange.has(startKey)) push(ensure(startKey).salidas, gkey, b);
                    if (inRange.has(endKey)) push(ensure(endKey).retornos, gkey, b);
                }
            }
        }
        const res = [];
        for (const d of this.rangeDays) {
            const e = buckets[d.key];
            if (!e) continue;
            const sal = Object.values(e.salidas), ret = Object.values(e.retornos);
            if (!sal.length && !ret.length) continue;
            res.push({
                key: d.key, label: d.full, isToday: d.isToday,
                salidas: sal.map((g) => this._agendaItem(g)),
                retornos: ret.map((g) => this._agendaItem(g)),
            });
        }
        return res;
    }
    agendaOpen(rep) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "rental.serial.reservation",
            res_id: rep, views: [[false, "form"]],
        });
    }

    // --- group by customer / order (swimlanes) ---
    get customerGroups() {
        const groups = new Map();
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                for (const b of s.blocks) {
                    const isMaint = b._isDowntime;
                    const key = isMaint ? "__maint" : (b.partner || "—");
                    const title = isMaint ? "Mantenimiento / Bloqueos" : (b.partner || "Sin cliente");
                    if (!groups.has(key)) groups.set(key, { key, title, isMaint, serials: new Map() });
                    const g = groups.get(key);
                    if (!g.serials.has(s.lot_id)) {
                        g.serials.set(s.lot_id, {
                            lot_id: s.lot_id, lot_name: s.lot_name,
                            product_name: p.product_name, blocks: [],
                        });
                    }
                    g.serials.get(s.lot_id).blocks.push(b);
                }
            }
        }
        return [...groups.values()]
            .map((g) => ({
                key: g.key, title: g.title, isMaint: g.isMaint,
                initials: g.isMaint ? "" : avatarInitials(g.title),
                avatarColor: g.isMaint ? "#64748b" : avatarColor(g.title),
                serials: [...g.serials.values()],
            }))
            .sort((a, b) => (a.isMaint ? 1 : 0) - (b.isMaint ? 1 : 0) || a.title.localeCompare(b.title));
    }

    // ------------------------------------------------------------------
    // Interactions
    // ------------------------------------------------------------------
    toggleProduct(productId) {
        this.state.expanded[productId] = !this.state.expanded[productId];
    }
    onBlockClick(block) { this.state.selected = block; this.state.tooltip = null; this.state.showDowntime = false; }
    closePanel() { this.state.selected = null; }
    async refresh() { await this.loadBoard(); }

    setDensity(d) {
        this.state.density = d;
        try { window.localStorage.setItem("aq_rental_density", d); } catch (e) { /* ignore */ }
    }
    toggleLegend() { this.state.legendCollapsed = !this.state.legendCollapsed; }
    onSearch(ev) { this.state.search = ev.target.value; }
    clearSearch() { this.state.search = ""; }

    setZoom(zoom) {
        this.state.zoom = zoom;
        const start = this.rangeStart;
        this.state.dateEnd = isoDate(
            zoom === "day" ? addDaysUTC(start, 2)
                : zoom === "week" ? addDaysUTC(start, 14) : addMonthsUTC(start, 3));
        this.loadBoard();
    }
    shift(direction) {
        const days = this.state.zoom === "month" ? 30 : (this.state.zoom === "week" ? 7 : 1);
        this.state.dateStart = isoDate(addDaysUTC(this.rangeStart, direction * days));
        this.state.dateEnd = isoDate(addDaysUTC(this.rangeEnd, direction * days));
        this.loadBoard();
    }
    goToday() {
        this.state.dateStart = isoDate(new Date());
        if (this.state.viewMode === "month") this.setViewMode("month");
        else this.setZoom(this.state.zoom);
    }
    onFilterChange(field, ev) {
        const val = ev.target.value;
        this.state.filters[field] = val ? (field === "states" ? [val] : parseInt(val)) : null;
        this.loadBoard();
    }
    clearFilters() {
        this.state.filters.warehouse_id = null;
        this.state.filters.package_id = null;
        this.state.filters.states = null;
        this.state.filters.partner_id = null;
        this.loadBoard();
    }
    onDateChange(field, ev) { this.state[field] = ev.target.value; this.loadBoard(); }

    // ------------------------------------------------------------------
    // Tooltip (on demand; positioned once on enter, not on mousemove)
    // ------------------------------------------------------------------
    onBlockEnter(ev, block) {
        const x = Math.min(ev.clientX + 16, window.innerWidth - 340);
        const y = Math.min(ev.clientY + 14, window.innerHeight - 240);
        this.state.tooltip = { block, x: Math.max(x, 8), y: Math.max(y, 8) };
    }
    onBlockLeave() { this.state.tooltip = null; }

    // ------------------------------------------------------------------
    // Quick actions
    // ------------------------------------------------------------------
    openSaleOrder(block) {
        if (!block.sale_order_id) {
            this.notification.add("No hay pedido de venta vinculado.", { type: "warning" });
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "sale.order",
            res_id: block.sale_order_id, views: [[false, "form"]],
        });
    }
    openReservation(block) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: block.type === "downtime" ? "rental.serial.downtime" : "rental.serial.reservation",
            res_id: block.id, views: [[false, "form"]],
        });
    }
    async releaseReservation(block) {
        try {
            await this.orm.call("rental.serial.reservation", "release_reservations", [[block.id]]);
            this.notification.add("Serie liberada.", { type: "success" });
            this.state.selected = null;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("No se pudo liberar: " + (e.message || e), { type: "danger" });
        }
    }
    viewConflict(block) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Conflictos de la serie",
            res_model: "rental.serial.reservation",
            views: [[false, "list"], [false, "form"]],
            domain: [["lot_id.name", "=", block.lot_name], ["conflict_status", "=", "conflict"]],
        });
    }
    viewHistory(serial) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Historial · " + serial.lot_name,
            res_model: "rental.serial.reservation",
            views: [[false, "list"], [false, "form"]],
            domain: [["lot_id", "=", serial.lot_id]],
        });
    }
    reserveSerial(serial, product) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Nueva reserva · " + serial.lot_name,
            res_model: "rental.serial.reservation",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_product_id: product.product_id,
                default_lot_id: serial.lot_id,
                default_reservation_block_start: toServer(this.rangeStart),
                default_reservation_block_end: toServer(this.rangeEnd),
            },
        });
    }
    viewAvailability(product) {
        this.state.search = "";
        this.state.filters.product_ids = [product.product_id];
        this.loadBoard();
    }
    async copySerial(serial) {
        try {
            await navigator.clipboard.writeText(serial.lot_name);
            this.notification.add(`Copiado: ${serial.lot_name}`, { type: "success" });
        } catch (e) {
            this.notification.add("No se pudo copiar.", { type: "warning" });
        }
    }

    // ------------------------------------------------------------------
    // Downtime quick form
    // ------------------------------------------------------------------
    startDowntime(lotId) {
        const now = new Date();
        const local = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
            + `T${pad(now.getHours())}:${pad(now.getMinutes())}`;
        this.state.showDowntime = true;
        this.state.selected = null;
        this.state.downtimeForm = { lot_id: lotId, reason: "maintenance", start: local, end: "" };
    }
    async submitDowntime() {
        const f = this.state.downtimeForm;
        if (!f.lot_id || !f.start) {
            this.notification.add("La serie y la fecha de inicio son obligatorias.", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("rental.serial.reservation", "create_downtime_quick", [], {
                lot_id: f.lot_id, reason: f.reason,
                start: toServer(new Date(f.start)),
                end: f.end ? toServer(new Date(f.end)) : null,
            });
            this.notification.add("Bloqueo creado.", { type: "success" });
            this.state.showDowntime = false;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("No se pudo crear el bloqueo: " + (e.message || e), { type: "danger" });
        }
    }
}

registry.category("actions").add("aq_rental_planning_board", RentalPlanningBoard);
```

## ./static/src/planning/planning_board.scss
```scss
// ===========================================================================
// AQ Rental Serial Planning — Planning board design system (iteration 3)
// AlphaQueb visual language: teal accent, soft elevation, segmented controls.
// ===========================================================================
$aq-accent: #0e7c86;
$aq-accent-2: #19c3d6;
$aq-ink: #0f172a;
$aq-text: #111827;
$aq-muted: #64748b;
$aq-faint: #94a3b8;
$aq-line: #e6eaf0;
$aq-bg: #f4f7fb;
$aq-surface: #ffffff;

$aq-states: (
    draft: #cbd5e1, quotation: #94a3b8, soft_hold: #f59e0b, reserved: #38bdf8,
    prepared: #7c3aed, picked_up: #2563eb, delivered: #10b981, in_use: #15803d,
    returned: #f97316, released: #d1d5db, maintenance: #4b5563, conflict: #dc2626,
    available: #e5e7eb,
);
$aq-light-states: (draft, quotation, released, available);
$aq-occ: (free: (#dcfce7, #166534), low: (#bbf7d0, #166534), mid: (#fef9c3, #854d0e),
          high: (#fed7aa, #9a3412), full: (#fecaca, #991b1b), none: (#f1f5f9, #94a3b8));

$aq-label-w: 296px;
$aq-label-w-compact: 240px;
$aq-shadow-sm: 0 1px 2px rgba(15, 23, 42, .06);
$aq-shadow-md: 0 4px 14px rgba(15, 23, 42, .1);
$aq-shadow-lg: 0 12px 34px rgba(15, 23, 42, .16);

// ---------------------------------------------------------------------------
.aq_planning_view {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background: $aq-bg;
    color: $aq-text;
    font-size: 13px;
    -webkit-font-smoothing: antialiased;

    * { box-sizing: border-box; }

    // thin custom scrollbars
    *::-webkit-scrollbar { width: 10px; height: 10px; }
    *::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 8px; border: 2px solid transparent; background-clip: content-box; }
    *::-webkit-scrollbar-thumb:hover { background: #94a3b8; background-clip: content-box; }
    *::-webkit-scrollbar-track { background: transparent; }

    .o_input {
        border: 1px solid $aq-line;
        border-radius: 8px;
        height: 32px;
        background: $aq-surface;
        transition: border-color .12s, box-shadow .12s;
        &:focus { border-color: $aq-accent; box-shadow: 0 0 0 3px rgba(14, 124, 134, .14); outline: none; }
    }

    // ===================================================== toolbar
    .aq_pb_toolbar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        background: $aq-surface;
        border-bottom: 1px solid $aq-line;
        box-shadow: $aq-shadow-sm;
        z-index: 50;

        .aq_pb_nav { display: flex; align-items: center; gap: 6px; }
        .aq_pb_nav .btn {
            width: 32px; height: 32px; padding: 0; border-radius: 8px;
            border: 1px solid $aq-line; background: $aq-surface; color: $aq-muted;
            display: inline-flex; align-items: center; justify-content: center;
            transition: all .12s;
            &:hover { background: #f1f5f9; color: $aq-ink; border-color: #cbd5e1; }
        }
        .aq_today_btn { width: auto !important; padding: 0 12px !important; font-weight: 700; color: $aq-accent !important; }
        input.o_input { width: auto; min-width: 132px; }

        // segmented controls (modes / zoom / density)
        .btn-group {
            background: #eef2f7;
            border-radius: 10px;
            padding: 3px;
            gap: 2px;
            box-shadow: inset 0 1px 2px rgba(15, 23, 42, .05);
            .btn {
                border: none !important;
                border-radius: 7px !important;
                background: transparent;
                color: $aq-muted;
                font-weight: 600;
                box-shadow: none !important;
                padding: 4px 12px;
                transition: all .12s;
                &:hover { color: $aq-ink; }
            }
            .btn.btn-primary, .btn.btn-secondary {
                background: $aq-surface;
                color: $aq-accent;
                box-shadow: $aq-shadow-sm;
            }
        }
        .aq_pb_modes .btn i { opacity: .9; }

        .aq_pb_search {
            position: relative;
            display: flex;
            align-items: center;
            flex: 1;
            min-width: 220px;
            max-width: 440px;
            > i.fa-search { position: absolute; left: 12px; color: $aq-faint; pointer-events: none; }
            input { width: 100%; padding-left: 32px; border-radius: 999px; }
            .aq_search_clear {
                position: absolute; right: 8px; border: none; background: transparent;
                color: $aq-faint; cursor: pointer; &:hover { color: $aq-ink; }
            }
        }
    }
    @media (max-width: 1100px) { .aq_pb_modes .aq_mode_label { display: none; } }

    // ===================================================== filters
    .aq_pb_filters_row {
        display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
        padding: 8px 14px;
        background: $aq-surface;
        border-bottom: 1px solid $aq-line;
        select.o_input { width: auto; min-width: 152px; }

        .aq_active_chips { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-left: auto; }
        .aq_chip {
            font-size: 11px; padding: 3px 10px; border-radius: 999px;
            background: #f1f5f9; color: $aq-muted; border: 1px solid $aq-line;
            &.is-active { background: rgba(14, 124, 134, .1); color: $aq-accent; border-color: rgba(14, 124, 134, .3); font-weight: 700; }
            .aq_chip_label { font-weight: 700; }
        }
    }

    // ===================================================== KPI cards
    .aq_planning_kpis {
        display: flex; flex-wrap: wrap; gap: 10px;
        padding: 12px 14px;
        background: linear-gradient(180deg, $aq-bg, $aq-surface);
        border-bottom: 1px solid $aq-line;

        .aq_kpi_chip {
            display: inline-flex; align-items: center; gap: 10px;
            padding: 9px 14px 9px 11px;
            border-radius: 12px;
            background: $aq-surface;
            border: 1px solid $aq-line;
            box-shadow: $aq-shadow-sm;
            transition: transform .12s, box-shadow .12s;
            &:hover { transform: translateY(-1px); box-shadow: $aq-shadow-md; }

            .aq_kpi_icon {
                width: 30px; height: 30px; border-radius: 9px;
                display: inline-flex; align-items: center; justify-content: center;
                background: #f1f5f9; color: $aq-muted; font-size: 14px;
            }
            .aq_kpi_text { display: flex; flex-direction: column; line-height: 1.1; }
            .aq_kpi_value { font-weight: 800; font-size: 18px; letter-spacing: -.3px; }
            .aq_kpi_label { color: $aq-faint; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .4px; }

            &.is-ok { .aq_kpi_icon { background: #dcfce7; color: #16a34a; } .aq_kpi_value { color: #15803d; } }
            &.is-busy { .aq_kpi_icon { background: #dbeafe; color: #2563eb; } .aq_kpi_value { color: #1d4ed8; } }
            &.is-warn { .aq_kpi_icon { background: #fef3c7; color: #d97706; } .aq_kpi_value { color: #b45309; } }
            &.is-danger { border-color: #fecaca; .aq_kpi_icon { background: #fee2e2; color: #dc2626; } .aq_kpi_value { color: #b91c1c; } }
            &.is-muted { .aq_kpi_icon { background: #e5e7eb; color: #4b5563; } }
        }
    }

    // ===================================================== legend
    .aq_rental_legend {
        display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
        padding: 7px 14px;
        background: $aq-surface;
        border-bottom: 1px solid $aq-line;
        font-size: 11px;

        .aq_legend_toggle {
            border: none; background: transparent; font-weight: 800; color: $aq-muted;
            cursor: pointer; text-transform: uppercase; font-size: 10.5px; letter-spacing: .5px;
        }
        .aq_rental_legend_group { display: flex; align-items: center; gap: 8px; padding-right: 12px; border-right: 1px solid $aq-line; }
        .aq_rental_legend_group_title { font-weight: 800; font-size: 9.5px; color: $aq-faint; text-transform: uppercase; letter-spacing: .5px; }
        .aq_legend_item { display: inline-flex; align-items: center; gap: 5px; color: #374151; }
        .aq_legend_swatch { width: 12px; height: 12px; border-radius: 4px; display: inline-block; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .06); }
    }

    // ===================================================== empty / loading
    .aq_pb_loading, .aq_pb_noresult {
        flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 12px; padding: 56px 20px; text-align: center; color: $aq-faint;
        i { font-size: 34px; opacity: .5; }
        span { font-size: 14px; }
    }
    .aq_pb_loading { flex-direction: row; i { font-size: 18px; } }

    // ===================================================== grid (timeline / customer)
    .aq_pb_grid { flex: 1; overflow: auto; position: relative; background: $aq-surface; }

    .aq_timeline_header { display: flex; position: sticky; top: 0; z-index: 30; background: $aq-surface; box-shadow: 0 2px 6px rgba(15, 23, 42, .05); }
    .aq_resource_column_header {
        width: $aq-label-w; min-width: $aq-label-w; padding: 10px 14px;
        font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: $aq-muted;
        position: sticky; left: 0; top: 0; z-index: 40; background: $aq-surface; border-right: 1px solid $aq-line;
    }
    .aq_resource_column {
        width: $aq-label-w; min-width: $aq-label-w; padding: 5px 14px;
        position: sticky; left: 0; z-index: 15; background: inherit; border-right: 1px solid $aq-line;
    }
    .aq_pb_timeline { position: relative; flex: 1; min-width: 740px; }

    .aq_colhead {
        position: absolute; top: 0; padding: 7px 6px; font-size: 11px; font-weight: 700; color: $aq-muted; white-space: nowrap;
        &.aq_timeline_weekend { color: #c2410c; }
        &.aq_timeline_today { color: $aq-accent; }
    }
    .aq_timeline_cell { position: absolute; top: 0; bottom: 0; border-right: 1px solid #eef2f7; }
    .aq_gridlines .aq_timeline_cell.aq_timeline_weekend { background: rgba(251, 146, 60, .05); width: 0; }
    .aq_today_line { position: absolute; top: 0; bottom: 0; width: 2px; z-index: 8; pointer-events: none;
        background: linear-gradient(180deg, $aq-accent-2, $aq-accent); box-shadow: 0 0 6px rgba(25, 195, 214, .5); }

    // ----- rows
    .aq_product_row {
        display: flex; cursor: pointer; border-bottom: 1px solid #eef2f7;
        background: linear-gradient(180deg, #f3f8fc, #eaf2f8);
        transition: background .12s;
        &:hover { background: linear-gradient(180deg, #eaf3fb, #e0ecf6); }
        .aq_resource_column { background: transparent; font-weight: 700; }
        &.is-maint { background: linear-gradient(180deg, #f8fafc, #eef2f7); .aq_resource_column { color: #475569; } }
    }
    .aq_product_summary {
        display: flex; align-items: center; justify-content: space-between; gap: 8px;
        // Full names, never truncated -> wrap onto multiple lines.
        .aq_product_name { display: flex; align-items: flex-start; gap: 7px; flex: 1; min-width: 0;
            white-space: normal; overflow: visible; line-height: 1.25; word-break: break-word;
            i { margin-top: 3px; flex: 0 0 auto; } }
    }
    .aq_product_availability_badge {
        flex: 0 0 auto; align-self: center;
        font-size: 10px; font-weight: 800; padding: 3px 9px; border-radius: 999px;
        background: #e5e7eb; color: $aq-text; white-space: nowrap; letter-spacing: .2px;
        &.is-ok { background: #dcfce7; color: #15803d; }
        &.is-warning { background: #fef3c7; color: #b45309; }
        &.is-full { background: #fee2e2; color: #b91c1c; }
    }
    .aq_customer_avatar {
        width: 26px; height: 26px; border-radius: 50%; color: #fff;
        display: inline-flex; align-items: center; justify-content: center;
        font-size: 10.5px; font-weight: 800; letter-spacing: .3px;
        box-shadow: $aq-shadow-sm; flex: 0 0 auto;
    }

    .aq_serial_row {
        display: flex; min-height: 40px; border-bottom: 1px solid #f1f5f9; background: $aq-surface;
        transition: background .1s;
        &:hover { background: #f8fbfd; }
        &.aq_empty { color: $aq-faint; }
    }
    .aq_serial_label { display: flex; align-items: center; gap: 7px; flex-wrap: wrap;
        .aq_serial_name { display: inline-flex; align-items: center; font-weight: 600; color: #334155;
            font-variant-numeric: tabular-nums; white-space: normal; word-break: break-word; }
        small { white-space: normal; word-break: break-word; } }
    .aq_serial_badge {
        font-size: 9.5px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
        background: #eef2f7; color: #475569; white-space: nowrap; letter-spacing: .2px;
    }
    .aq_serial_actions {
        display: inline-flex; gap: 2px; margin-left: auto; opacity: 0; transform: translateX(4px);
        transition: opacity .14s, transform .14s;
        button {
            border: none; background: transparent; color: $aq-faint; padding: 3px 6px; cursor: pointer; border-radius: 6px;
            &:hover { background: #e2e8f0; color: $aq-accent; }
        }
    }
    .aq_serial_row:hover .aq_serial_actions { opacity: 1; transform: none; }

    // ----- reservation blocks
    .aq_reservation_block {
        position: absolute; top: 5px; height: 30px;
        border-radius: 8px; padding: 4px 9px;
        font-size: 12px; line-height: 1.15; color: #fff;
        overflow: hidden; cursor: pointer; z-index: 2;
        background-image: linear-gradient(180deg, rgba(255, 255, 255, .2), rgba(255, 255, 255, 0));
        box-shadow: 0 1px 2px rgba(15, 23, 42, .22), inset 0 1px 0 rgba(255, 255, 255, .25);
        border: 1px solid rgba(15, 23, 42, .06);
        transition: transform .1s ease, box-shadow .1s ease, filter .1s ease;
        &:hover, &:focus { transform: translateY(-1px); box-shadow: $aq-shadow-md; z-index: 20; outline: none; filter: saturate(1.05); }

        .aq_block_billable {
            position: absolute; top: 0; bottom: 0; background: rgba(255, 255, 255, .26);
            border-left: 1px dashed rgba(255, 255, 255, .7); border-right: 1px dashed rgba(255, 255, 255, .7); pointer-events: none;
        }
        .aq_block_conflict_icon, .aq_block_overdue_icon { float: right; margin-left: 4px; opacity: .95; }
        .aq_block_customer { font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; position: relative; text-shadow: 0 1px 1px rgba(0, 0, 0, .12); }
        .aq_block_main { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; position: relative; opacity: .96; }
        .aq_block_dates { font-size: 10px; opacity: .82; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; position: relative; }

        &.is-compact { padding: 3px 6px; .aq_block_customer, .aq_block_dates { display: none; } .aq_block_main { font-size: 11px; } }
        &.is-medium .aq_block_dates { display: none; }
    }
    @each $k, $c in $aq-states {
        .aq_reservation_block.aq_state_#{$k} { background-color: $c; }
        .aq_serial_badge.aq_state_#{$k} { background: mix($c, #ffffff, 22%); color: darken($c, 24%); }
    }
    @each $k in $aq-light-states {
        .aq_reservation_block.aq_state_#{$k} { color: #1f2937; text-shadow: none;
            .aq_block_customer { text-shadow: none; } .aq_block_billable { background: rgba(15, 23, 42, .08); border-color: rgba(15, 23, 42, .15); } }
    }
    .aq_reservation_block.aq_is_downtime, .aq_reservation_block.aq_state_maintenance {
        background-image: repeating-linear-gradient(45deg, #4b5563, #4b5563 7px, #6b7280 7px, #6b7280 14px);
    }
    .aq_reservation_block.aq_state_soft_hold { border: 1px dashed #b45309; }
    .aq_reservation_block.aq_state_released { opacity: .6; color: #475569; }
    .aq_reservation_block.is-overdue { box-shadow: 0 0 0 2px rgba(249, 115, 22, .6), $aq-shadow-sm; }
    .aq_reservation_block.has-conflict {
        background-color: #dc2626; background-image: linear-gradient(180deg, rgba(255, 255, 255, .2), rgba(255, 255, 255, 0));
        border: 2px solid #991b1b; color: #fff; z-index: 10; animation: aqConflictPulse 1.8s ease-in-out infinite;
    }

    // ===================================================== HEATMAP
    .aq_heatmap { flex: 1; overflow: hidden; display: flex; flex-direction: column; background: $aq-surface; }
    .aq_hm_legend {
        display: flex; align-items: center; gap: 6px; padding: 10px 14px; font-size: 12px; color: $aq-muted; border-bottom: 1px solid $aq-line;
        .aq_hm_cell { width: 22px; min-width: 22px; height: 16px; border-radius: 4px; }
    }
    .aq_hm_scroll { flex: 1; overflow: auto; padding: 6px 8px 14px; }
    .aq_hm_row { display: flex; align-items: center; gap: 4px; padding: 2px 0; }
    .aq_hm_row.aq_hm_head { position: sticky; top: 0; z-index: 5; background: $aq-surface; padding-bottom: 6px; }
    .aq_hm_label {
        width: 240px; min-width: 240px; padding: 6px 12px; font-size: 13px;
        position: sticky; left: 0; background: $aq-surface; z-index: 2; cursor: pointer; border-radius: 8px;
        white-space: normal; word-break: break-word; line-height: 1.25;
        &:hover { background: #f1f5f9; }
    }
    .aq_hm_colhead { flex: 1; min-width: 34px; text-align: center; font-size: 11px; font-weight: 700; color: $aq-muted; padding: 4px 2px;
        &.aq_timeline_weekend { color: #c2410c; } &.aq_timeline_today { color: $aq-accent; } }
    .aq_hm_cell {
        flex: 1; min-width: 34px; height: 34px; margin: 0 2px; border-radius: 7px;
        display: inline-flex; align-items: center; justify-content: center;
        font-size: 11px; font-weight: 800; cursor: pointer; transition: transform .1s, box-shadow .1s;
        box-shadow: inset 0 0 0 1px rgba(15, 23, 42, .04);
        &:hover { transform: scale(1.12); box-shadow: $aq-shadow-md; z-index: 3; }
    }
    @each $k, $pair in $aq-occ {
        .aq_hm_cell.lvl-#{$k} { background: nth($pair, 1); color: nth($pair, 2); }
        .aq_month_cell.lvl-#{$k} { background: nth($pair, 1); color: nth($pair, 2); }
    }

    // ===================================================== MONTH
    .aq_month_view { flex: 1; overflow: auto; display: flex; flex-direction: column; padding: 16px 18px; background: $aq-bg; }
    .aq_month_toolbar {
        display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
        .btn { width: 32px; height: 32px; padding: 0; border-radius: 8px; border: 1px solid $aq-line; background: $aq-surface; color: $aq-muted; }
        .aq_month_label { font-size: 19px; font-weight: 800; min-width: 170px; text-align: center; letter-spacing: -.3px; }
        select.o_input { width: auto; max-width: 300px; }
        .aq_hm_legend { border: none; padding: 0; gap: 4px; margin-left: auto;
            .aq_hm_cell { width: 16px; min-width: 16px; height: 14px; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .06); } }
    }
    .aq_month_grid { flex: 1; display: flex; flex-direction: column; gap: 8px; }
    .aq_month_weekhead, .aq_month_week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }
    .aq_month_weekhead > div { text-align: center; font-size: 10.5px; font-weight: 800; color: $aq-faint; text-transform: uppercase; letter-spacing: .5px;
        &.is-we { color: #c2410c; } }
    .aq_month_week { flex: 1; }
    .aq_month_cell {
        position: relative; border-radius: 12px; padding: 8px 10px 10px; min-height: 76px;
        display: flex; flex-direction: column; cursor: pointer; overflow: hidden;
        box-shadow: inset 0 0 0 1px rgba(15, 23, 42, .05); transition: transform .1s, box-shadow .1s;
        &:hover { transform: translateY(-2px); box-shadow: $aq-shadow-md; }
        &.is-empty { background: transparent !important; box-shadow: none; cursor: default; }
        &.is-today { box-shadow: inset 0 0 0 2px $aq-accent; }
        .aq_month_daynum { position: absolute; top: 6px; right: 10px; font-size: 12px; font-weight: 800; opacity: .5; }
        .aq_month_free { font-size: 22px; font-weight: 900; margin-top: auto; letter-spacing: -.5px; small { font-size: 12px; font-weight: 700; opacity: .6; } }
        .aq_month_freelabel { font-size: 9px; text-transform: uppercase; letter-spacing: .6px; opacity: .75; font-weight: 700; }
        .aq_month_bar { height: 5px; border-radius: 999px; background: rgba(15, 23, 42, .1); margin: 5px 0 4px; overflow: hidden;
            span { display: block; height: 100%; border-radius: 999px; background: rgba(15, 23, 42, .35); } }
    }
    .aq_month_cell.lvl-full .aq_month_bar span { background: #dc2626; }
    .aq_month_cell.lvl-high .aq_month_bar span { background: #ea580c; }
    .aq_month_cell.lvl-mid .aq_month_bar span { background: #d97706; }

    // ===================================================== AGENDA
    .aq_agenda_view { flex: 1; overflow: auto; padding: 18px 22px; background: $aq-bg; }
    .aq_agenda_day {
        position: relative; padding: 2px 0 6px 26px; margin-bottom: 16px;
        &::before { content: ""; position: absolute; left: 7px; top: 6px; bottom: -16px; width: 2px; background: $aq-line; }
        &::after { content: ""; position: absolute; left: 1px; top: 5px; width: 14px; height: 14px; border-radius: 50%; background: $aq-surface; box-shadow: inset 0 0 0 3px #cbd5e1; }
        &:last-child::before { display: none; }
        &.is-today::after { box-shadow: inset 0 0 0 3px $aq-accent; }
    }
    .aq_agenda_date { font-weight: 800; font-size: 15px; margin-bottom: 10px; text-transform: capitalize; color: $aq-ink; }
    .aq_agenda_today_tag { background: $aq-accent; color: #fff; font-size: 9.5px; font-weight: 800; padding: 2px 8px; border-radius: 999px; margin-left: 8px; vertical-align: middle; letter-spacing: .5px; }
    .aq_agenda_cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 820px) { .aq_agenda_cols { grid-template-columns: 1fr; } }
    .aq_agenda_col { background: $aq-surface; border: 1px solid $aq-line; border-radius: 12px; padding: 12px 14px; box-shadow: $aq-shadow-sm; }
    .aq_agenda_col_title { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .4px; margin-bottom: 8px;
        &.aq_out { color: #1d4ed8; } &.aq_in { color: #b45309; } }
    .aq_agenda_empty { color: #cbd5e1; padding: 6px 0; }
    .aq_agenda_item {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        padding: 8px 10px; border-radius: 9px; margin-bottom: 6px; cursor: pointer;
        background: #f8fafc; border: 1px solid transparent; transition: all .1s;
        &:hover { background: #fff; border-color: #cbd5e1; box-shadow: $aq-shadow-sm; transform: translateX(2px); }
        .aq_agenda_qty { font-weight: 800; color: $aq-ink; }
        .aq_agenda_partner { color: $aq-muted; font-size: 12px; }
        .aq_agenda_state { margin-left: auto; }
    }

    // ===================================================== density
    &.is-density-compact {
        font-size: 12px;
        .aq_serial_row { min-height: 30px; }
        .aq_reservation_block { font-size: 11px; padding: 2px 7px; border-radius: 6px; top: 4px; height: 24px; }
        .aq_resource_column, .aq_resource_column_header { width: $aq-label-w-compact; min-width: $aq-label-w-compact; }
        .aq_planning_kpis { padding: 8px 14px; .aq_kpi_value { font-size: 16px; } }
    }
}

@keyframes aqConflictPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, .4); }
    50% { box-shadow: 0 0 0 5px rgba(220, 38, 38, .12); }
}
@media (prefers-reduced-motion: reduce) {
    .aq_planning_view .aq_reservation_block.has-conflict { animation: none; }
}

// ===================================================== tooltip (glass)
.aq_rental_tooltip {
    position: fixed; z-index: 1080; width: 326px; max-width: 92vw;
    background: rgba(15, 23, 42, .96); color: #e2e8f0; border-radius: 12px; padding: 13px 15px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, .4); pointer-events: none; font-size: 12px;
    border: 1px solid rgba(255, 255, 255, .08);
    -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);

    .aq_tt_head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; }
    .aq_tt_folio { font-weight: 800; font-size: 14px; color: #fff; letter-spacing: -.2px; }
    .aq_tt_alert { background: rgba(220, 38, 38, .22); color: #fecaca; padding: 5px 9px; border-radius: 7px; margin-bottom: 8px; font-weight: 700; }
    .aq_tt_table { width: 100%; border-collapse: collapse;
        td { padding: 2.5px 0; vertical-align: top; }
        td:first-child { color: #94a3b8; width: 84px; text-transform: uppercase; font-size: 9.5px; font-weight: 800; letter-spacing: .4px; }
        td:last-child { color: #f1f5f9; }
    }
    .aq_serial_badge { background: rgba(255, 255, 255, .16); color: #fff; font-size: 10px; font-weight: 700; padding: 2px 9px; border-radius: 999px; }
}

// ===================================================== drawer
.aq_reservation_drawer {
    position: absolute; top: 0; right: 0; bottom: 0; width: 430px; max-width: 92vw;
    background: $aq-surface; border-left: 1px solid $aq-line; box-shadow: $aq-shadow-lg;
    z-index: 60; display: flex; flex-direction: column;
    animation: aqDrawerIn .18s ease;

    .aq_drawer_header { padding: 20px 24px 18px; border-bottom: 1px solid $aq-line; background: linear-gradient(180deg, #f8fafc, #ffffff); }
    .aq_drawer_title_row { display: flex; align-items: center; justify-content: space-between; }
    .aq_drawer_title { font-size: 23px; font-weight: 800; color: $aq-ink; letter-spacing: -.5px; }
    .aq_drawer_header .btn { border: 1px solid $aq-line; border-radius: 8px; width: 30px; height: 30px; padding: 0; }
    .aq_drawer_badge { display: inline-block; margin-top: 10px; font-size: 11px; padding: 4px 12px; font-weight: 700; }
    .aq_drawer_alert { margin-top: 11px; background: #fee2e2; color: #b91c1c; padding: 7px 11px; border-radius: 8px; font-weight: 700; font-size: 12px; }

    .aq_drawer_body { flex: 1; overflow: auto; }
    .aq_drawer_section { padding: 15px 24px; border-bottom: 1px solid #f1f5f9; }
    .aq_drawer_label { font-size: 10px; font-weight: 800; text-transform: uppercase; color: $aq-faint; letter-spacing: .6px; margin-bottom: 5px; }
    .aq_drawer_value { font-size: 15px; color: $aq-text; }
    .aq_drawer_customer { font-size: 19px; font-weight: 800; letter-spacing: -.3px; }
    .aq_drawer_link { color: $aq-accent; cursor: pointer; font-weight: 700; margin-top: 5px; display: inline-block; &:hover { text-decoration: underline; } }
    .aq_drawer_duration { font-size: 12px; color: $aq-muted; margin-top: 3px; font-weight: 600; }
    .aq_drawer_actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 16px 24px; border-top: 1px solid $aq-line; background: #f8fafc; }
    .aq_drawer_actions .btn { border-radius: 8px; font-weight: 600; }

    @each $k, $c in (draft: #cbd5e1, quotation: #94a3b8, soft_hold: #f59e0b, reserved: #38bdf8,
        prepared: #7c3aed, picked_up: #2563eb, delivered: #10b981, in_use: #15803d, returned: #f97316,
        released: #d1d5db, maintenance: #4b5563, conflict: #dc2626, available: #e5e7eb) {
        .aq_serial_badge.aq_state_#{$k} { background: mix($c, #ffffff, 22%); color: darken($c, 24%); }
    }
}
@keyframes aqDrawerIn { from { transform: translateX(18px); opacity: .4; } to { transform: none; opacity: 1; } }
```

## ./static/src/planning/planning_board.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="aq_rental_serial_planning.PlanningBoard">
        <div class="aq_planning_view" t-att-class="densityClass">

            <!-- ===== Toolbar ===== -->
            <div class="aq_pb_toolbar">
                <div class="aq_pb_nav">
                    <button class="btn btn-light" t-on-click="() => this.nav(-1)" aria-label="Anterior" title="Anterior">
                        <i class="fa fa-chevron-left"/>
                    </button>
                    <button class="btn btn-light aq_today_btn" t-on-click="() => this.goToday()" title="Ir a hoy">Hoy</button>
                    <input type="date" class="o_input" t-att-value="state.dateStart" aria-label="Fecha inicio"
                           t-on-change="(ev) => this.onDateChange('dateStart', ev)"/>
                    <span class="mx-1">→</span>
                    <input type="date" class="o_input" t-att-value="state.dateEnd" aria-label="Fecha fin"
                           t-on-change="(ev) => this.onDateChange('dateEnd', ev)"/>
                    <button class="btn btn-light" t-on-click="() => this.nav(1)" aria-label="Siguiente" title="Siguiente">
                        <i class="fa fa-chevron-right"/>
                    </button>
                    <button class="btn btn-light" t-on-click="() => this.refresh()" aria-label="Actualizar" title="Actualizar">
                        <i class="fa fa-refresh"/>
                    </button>
                </div>

                <!-- view-mode switcher -->
                <div class="aq_pb_modes btn-group" role="group" aria-label="Modo de vista">
                    <t t-foreach="viewModes" t-as="m" t-key="m.key">
                        <button class="btn btn-sm" t-att-class="state.viewMode === m.key ? 'btn-primary' : 'btn-light'"
                                t-on-click="() => this.setViewMode(m.key)" t-att-title="m.label">
                            <i t-attf-class="fa {{m.icon}}"/> <span class="aq_mode_label" t-esc="m.label"/>
                        </button>
                    </t>
                </div>

                <div t-if="showZoom" class="aq_pb_zoom btn-group" role="group" aria-label="Granularidad">
                    <button class="btn" t-att-class="state.zoom === 'day' ? 'btn-secondary' : 'btn-light'" t-on-click="() => this.setZoom('day')">Día</button>
                    <button class="btn" t-att-class="state.zoom === 'week' ? 'btn-secondary' : 'btn-light'" t-on-click="() => this.setZoom('week')">Sem</button>
                    <button class="btn" t-att-class="state.zoom === 'month' ? 'btn-secondary' : 'btn-light'" t-on-click="() => this.setZoom('month')">Mes</button>
                </div>

                <div class="aq_pb_search">
                    <i class="fa fa-search"/>
                    <input type="text" class="o_input" placeholder="Buscar producto, serie, cliente o folio…"
                           t-att-value="state.search" t-on-input="(ev) => this.onSearch(ev)" aria-label="Buscar"/>
                    <button t-if="searching" class="aq_search_clear" t-on-click="() => this.clearSearch()" aria-label="Limpiar búsqueda">
                        <i class="fa fa-times"/>
                    </button>
                </div>

                <div class="aq_pb_density btn-group" role="group" aria-label="Densidad">
                    <button class="btn btn-sm" t-att-class="state.density === 'comfortable' ? 'btn-secondary' : 'btn-light'"
                            t-on-click="() => this.setDensity('comfortable')" title="Cómodo"><i class="fa fa-bars"/></button>
                    <button class="btn btn-sm" t-att-class="state.density === 'compact' ? 'btn-secondary' : 'btn-light'"
                            t-on-click="() => this.setDensity('compact')" title="Compacto"><i class="fa fa-align-justify"/></button>
                </div>
            </div>

            <!-- ===== Filters row ===== -->
            <div class="aq_pb_filters_row">
                <select class="o_input" t-on-change="(ev) => this.onFilterChange('warehouse_id', ev)" aria-label="Almacén">
                    <option value="">Todos los almacenes</option>
                    <t t-foreach="state.meta.warehouses" t-as="w" t-key="w.id">
                        <option t-att-value="w.id" t-att-selected="state.filters.warehouse_id === w.id"><t t-esc="w.name"/></option>
                    </t>
                </select>
                <select class="o_input" t-on-change="(ev) => this.onFilterChange('package_id', ev)" aria-label="Paquete">
                    <option value="">Todos los paquetes</option>
                    <t t-foreach="state.meta.packages" t-as="p" t-key="p.id">
                        <option t-att-value="p.id" t-att-selected="state.filters.package_id === p.id"><t t-esc="p.name"/></option>
                    </t>
                </select>
                <select class="o_input" t-on-change="(ev) => this.onFilterChange('states', ev)" aria-label="Estado">
                    <option value="">Todos los estados</option>
                    <t t-foreach="state.meta.states" t-as="s" t-key="s.key">
                        <option t-att-value="s.key"><t t-esc="s.label"/></option>
                    </t>
                </select>
                <div class="aq_active_chips">
                    <t t-foreach="activeFilterChips" t-as="chip" t-key="chip.key">
                        <span class="aq_chip" t-att-class="chip.active ? 'is-active' : ''">
                            <span class="aq_chip_label" t-esc="chip.label"/>: <t t-esc="chip.value"/>
                        </span>
                    </t>
                    <button t-if="hasActiveFilters" class="btn btn-sm btn-link" t-on-click="() => this.clearFilters()">Limpiar filtros</button>
                </div>
            </div>

            <!-- ===== KPI bar ===== -->
            <div class="aq_planning_kpis">
                <t t-foreach="kpis" t-as="k" t-key="k.key">
                    <span class="aq_kpi_chip" t-att-class="k.cls">
                        <i t-attf-class="aq_kpi_icon fa {{k.icon}}"/>
                        <span class="aq_kpi_text">
                            <span class="aq_kpi_value" t-esc="k.value"/>
                            <span class="aq_kpi_label" t-esc="k.label"/>
                        </span>
                    </span>
                </t>
            </div>

            <!-- ===== Legend (state) ===== -->
            <div t-if="showStateLegend" class="aq_rental_legend">
                <button class="aq_legend_toggle" t-on-click="() => this.toggleLegend()"
                        t-att-aria-expanded="!state.legendCollapsed" aria-label="Mostrar u ocultar leyenda">
                    <i t-att-class="state.legendCollapsed ? 'fa fa-caret-right' : 'fa fa-caret-down'"/> Leyenda
                </button>
                <t t-if="!state.legendCollapsed">
                    <t t-foreach="legendGroups" t-as="g" t-key="g.title">
                        <div class="aq_rental_legend_group">
                            <span class="aq_rental_legend_group_title" t-esc="g.title"/>
                            <t t-foreach="g.items" t-as="it" t-key="it.key">
                                <span class="aq_legend_item" t-att-title="it.label">
                                    <span class="aq_legend_swatch" t-att-class="it.cls" t-attf-style="background:{{it.color}};"/>
                                    <t t-esc="it.label"/>
                                </span>
                            </t>
                        </div>
                    </t>
                </t>
            </div>

            <!-- ===== Loading ===== -->
            <div t-if="state.loading" class="aq_pb_loading">
                <i class="fa fa-spinner fa-spin"/> Cargando disponibilidad…
            </div>

            <t t-else="">
                <!-- ============================== TIMELINE ============================== -->
                <div t-if="state.viewMode === 'timeline'" class="aq_pb_grid">
                    <div class="aq_timeline_header">
                        <div class="aq_resource_column_header">Producto / Item</div>
                        <div class="aq_pb_timeline">
                            <t t-foreach="columns" t-as="col" t-key="col.key">
                                <div class="aq_colhead" t-att-class="{'aq_timeline_weekend': col.isWeekend, 'aq_timeline_today': col.isToday}"
                                     t-attf-style="left:{{col.left}}%;"><t t-esc="col.label"/></div>
                            </t>
                        </div>
                    </div>
                    <div class="aq_pb_body">
                        <t t-foreach="filteredProducts" t-as="product" t-key="product.product_id">
                            <div class="aq_product_row" t-on-click="() => this.toggleProduct(product.product_id)">
                                <div class="aq_resource_column aq_product_summary">
                                    <span class="aq_product_name">
                                        <i t-att-class="isExpanded(product) ? 'fa fa-caret-down' : 'fa fa-caret-right'"/>
                                        <strong t-esc="product.product_name"/>
                                    </span>
                                    <span class="aq_product_availability_badge" t-att-class="product._summary.badge">
                                        <t t-esc="product._summary.available"/>/<t t-esc="product._summary.total"/> disp.
                                        <t t-if="product._summary.blocked"> · <t t-esc="product._summary.blocked"/> ocup.</t>
                                    </span>
                                </div>
                                <div class="aq_pb_timeline aq_gridlines">
                                    <t t-foreach="columns" t-as="col" t-key="col.key">
                                        <div class="aq_timeline_cell" t-att-class="{'aq_timeline_weekend': col.isWeekend}" t-attf-style="left:{{col.left}}%;"/>
                                    </t>
                                </div>
                            </div>
                            <t t-if="isExpanded(product)">
                                <t t-foreach="product.serials" t-as="serial" t-key="serial.lot_id">
                                    <div class="aq_serial_row">
                                        <div class="aq_resource_column aq_serial_label">
                                            <span class="aq_serial_name"><i class="fa fa-barcode me-1 text-muted"/><t t-esc="serial.lot_name"/></span>
                                            <span t-att-class="serial._badgeClass" t-esc="serial._badgeLabel"/>
                                            <span class="aq_serial_actions">
                                                <button t-on-click.stop="() => this.viewHistory(serial)" title="Ver historial" aria-label="Ver historial"><i class="fa fa-history"/></button>
                                                <button t-on-click.stop="() => this.reserveSerial(serial, product)" title="Reservar esta serie" aria-label="Reservar"><i class="fa fa-calendar-plus-o"/></button>
                                                <button t-on-click.stop="() => this.startDowntime(serial.lot_id)" title="Crear mantenimiento / bloqueo" aria-label="Mantenimiento"><i class="fa fa-wrench"/></button>
                                                <button t-on-click.stop="() => this.copySerial(serial)" title="Copiar número de serie" aria-label="Copiar"><i class="fa fa-clone"/></button>
                                            </span>
                                        </div>
                                        <div class="aq_pb_timeline">
                                            <t t-foreach="columns" t-as="col" t-key="col.key">
                                                <div class="aq_timeline_cell" t-att-class="{'aq_timeline_weekend': col.isWeekend}" t-attf-style="left:{{col.left}}%;"/>
                                            </t>
                                            <t t-if="todayLineLeft !== null"><div class="aq_today_line" t-attf-style="left:{{todayLineLeft}}%;"/></t>
                                            <t t-foreach="serial.blocks" t-as="block" t-key="block.type + '_' + block.id">
                                                <t t-call="aq_rental_serial_planning.Block"/>
                                            </t>
                                        </div>
                                    </div>
                                </t>
                            </t>
                        </t>
                        <div t-if="!filteredProducts.length" class="aq_pb_noresult"><i class="fa fa-search"/><span>Ningún producto coincide con la búsqueda o los filtros.</span></div>
                    </div>
                </div>

                <!-- ============================== CLIENTE ============================== -->
                <div t-if="state.viewMode === 'customer'" class="aq_pb_grid">
                    <div class="aq_timeline_header">
                        <div class="aq_resource_column_header">Cliente / Item</div>
                        <div class="aq_pb_timeline">
                            <t t-foreach="columns" t-as="col" t-key="col.key">
                                <div class="aq_colhead" t-att-class="{'aq_timeline_weekend': col.isWeekend, 'aq_timeline_today': col.isToday}"
                                     t-attf-style="left:{{col.left}}%;"><t t-esc="col.label"/></div>
                            </t>
                        </div>
                    </div>
                    <div class="aq_pb_body">
                        <t t-foreach="customerGroups" t-as="group" t-key="group.key">
                            <div class="aq_product_row" t-att-class="group.isMaint ? 'is-maint' : ''">
                                <div class="aq_resource_column aq_product_summary">
                                    <span class="aq_product_name">
                                        <span class="aq_customer_avatar" t-attf-style="background:{{group.avatarColor}};">
                                            <t t-if="group.isMaint"><i class="fa fa-wrench"/></t>
                                            <t t-else="" t-esc="group.initials"/>
                                        </span>
                                        <strong t-esc="group.title"/>
                                    </span>
                                    <span class="aq_product_availability_badge"><t t-esc="group.serials.length"/> items</span>
                                </div>
                                <div class="aq_pb_timeline aq_gridlines">
                                    <t t-foreach="columns" t-as="col" t-key="col.key">
                                        <div class="aq_timeline_cell" t-att-class="{'aq_timeline_weekend': col.isWeekend}" t-attf-style="left:{{col.left}}%;"/>
                                    </t>
                                </div>
                            </div>
                            <t t-foreach="group.serials" t-as="serial" t-key="serial.lot_id">
                                <div class="aq_serial_row">
                                    <div class="aq_resource_column aq_serial_label">
                                        <span class="aq_serial_name"><i class="fa fa-barcode me-1 text-muted"/><t t-esc="serial.lot_name"/></span>
                                        <small class="text-muted" t-esc="serial.product_name"/>
                                    </div>
                                    <div class="aq_pb_timeline">
                                        <t t-foreach="columns" t-as="col" t-key="col.key">
                                            <div class="aq_timeline_cell" t-att-class="{'aq_timeline_weekend': col.isWeekend}" t-attf-style="left:{{col.left}}%;"/>
                                        </t>
                                        <t t-if="todayLineLeft !== null"><div class="aq_today_line" t-attf-style="left:{{todayLineLeft}}%;"/></t>
                                        <t t-foreach="serial.blocks" t-as="block" t-key="block.type + '_' + block.id">
                                            <t t-call="aq_rental_serial_planning.Block"/>
                                        </t>
                                    </div>
                                </div>
                            </t>
                        </t>
                        <div t-if="!customerGroups.length" class="aq_pb_noresult"><i class="fa fa-users"/><span>No hay reservas en el periodo seleccionado.</span></div>
                    </div>
                </div>

                <!-- ============================== CARGA / HEATMAP ============================== -->
                <div t-if="state.viewMode === 'heatmap'" class="aq_heatmap">
                    <div class="aq_hm_legend">
                        Ocupación:
                        <span class="aq_hm_cell lvl-free">0</span>
                        <span class="aq_hm_cell lvl-low"/><span class="aq_hm_cell lvl-mid"/>
                        <span class="aq_hm_cell lvl-high"/><span class="aq_hm_cell lvl-full">Lleno</span>
                        <small class="text-muted ms-2">(número = unidades libres)</small>
                    </div>
                    <div class="aq_hm_scroll">
                        <div class="aq_hm_row aq_hm_head">
                            <div class="aq_hm_label">Producto</div>
                            <t t-foreach="rangeDays" t-as="day" t-key="day.key">
                                <div class="aq_hm_colhead" t-att-class="{'aq_timeline_weekend': day.isWeekend, 'aq_timeline_today': day.isToday}" t-esc="day.label"/>
                            </t>
                        </div>
                        <t t-foreach="heatmapRows" t-as="row" t-key="row.product.product_id">
                            <div class="aq_hm_row">
                                <div class="aq_hm_label" t-on-click="() => this.heatDrill(row.product)" t-att-title="row.product.product_name">
                                    <strong t-esc="row.product.product_name"/>
                                    <small class="text-muted ms-1" t-esc="row.total + ' u.'"/>
                                </div>
                                <t t-foreach="row.cells" t-as="cell" t-key="cell.key">
                                    <div t-attf-class="aq_hm_cell lvl-{{cell.level}}"
                                         t-att-title="cell.free + ' libres de ' + cell.total"
                                         t-on-click="() => this.heatDrill(row.product)">
                                        <t t-if="cell.total" t-esc="cell.free"/>
                                    </div>
                                </t>
                            </div>
                        </t>
                        <div t-if="!heatmapRows.length" class="aq_pb_noresult">Sin productos.</div>
                    </div>
                </div>

                <!-- ============================== MES ============================== -->
                <div t-if="state.viewMode === 'month'" class="aq_month_view">
                    <div class="aq_month_toolbar">
                        <button class="btn btn-light btn-sm" t-on-click="() => this.monthShift(-1)"><i class="fa fa-chevron-left"/></button>
                        <span class="aq_month_label" t-esc="monthLabel"/>
                        <button class="btn btn-light btn-sm" t-on-click="() => this.monthShift(1)"><i class="fa fa-chevron-right"/></button>
                        <select class="o_input ms-3" t-on-change="(ev) => this.onMonthProductChange(ev)" aria-label="Producto">
                            <t t-foreach="monthProducts" t-as="mp" t-key="mp.product_id">
                                <option t-att-value="mp.product_id" t-att-selected="monthProduct ? mp.product_id === monthProduct.product_id : false"><t t-esc="mp.product_name"/></option>
                            </t>
                        </select>
                        <span class="aq_hm_legend ms-auto">
                            <span class="aq_hm_cell lvl-free"/>libre
                            <span class="aq_hm_cell lvl-mid"/>parcial
                            <span class="aq_hm_cell lvl-full"/>lleno
                        </span>
                    </div>
                    <div t-if="!monthProduct" class="aq_pb_noresult">Selecciona un producto.</div>
                    <div t-else="" class="aq_month_grid">
                        <div class="aq_month_weekhead">
                            <div>Lun</div><div>Mar</div><div>Mié</div><div>Jue</div><div>Vie</div><div class="is-we">Sáb</div><div class="is-we">Dom</div>
                        </div>
                        <t t-foreach="monthWeeks" t-as="week" t-key="week_index">
                            <div class="aq_month_week">
                                <t t-foreach="week" t-as="cell" t-key="cell_index">
                                    <div t-if="!cell" class="aq_month_cell is-empty"/>
                                    <div t-else="" t-att-class="cell.cls"
                                         t-on-click="() => this.monthDayDrill()">
                                        <div class="aq_month_daynum" t-esc="cell.day"/>
                                        <div class="aq_month_free"><t t-esc="cell.free"/><small>/<t t-esc="cell.total"/></small></div>
                                        <div class="aq_month_bar"><span t-attf-style="width:{{cell.pct}}%;"/></div>
                                        <div class="aq_month_freelabel">libres</div>
                                    </div>
                                </t>
                            </div>
                        </t>
                    </div>
                </div>

                <!-- ============================== AGENDA ============================== -->
                <div t-if="state.viewMode === 'agenda'" class="aq_agenda_view">
                    <t t-foreach="agendaDays" t-as="day" t-key="day.key">
                        <div class="aq_agenda_day" t-att-class="day.isToday ? 'is-today' : ''">
                            <div class="aq_agenda_date"><t t-esc="day.label"/><span t-if="day.isToday" class="aq_agenda_today_tag">HOY</span></div>
                            <div class="aq_agenda_cols">
                                <div class="aq_agenda_col">
                                    <div class="aq_agenda_col_title aq_out">▸ Salidas (preparar / entregar)</div>
                                    <div t-if="!day.salidas.length" class="aq_agenda_empty">—</div>
                                    <t t-foreach="day.salidas" t-as="it" t-key="it.label + it.rep">
                                        <div class="aq_agenda_item" t-on-click="() => this.agendaOpen(it.rep)">
                                            <span class="aq_agenda_qty" t-esc="it.label"/>
                                            <span class="aq_agenda_partner" t-if="it.partner" t-esc="it.partner"/>
                                            <span class="aq_serial_badge aq_agenda_state" t-esc="it.stateLabel"/>
                                        </div>
                                    </t>
                                </div>
                                <div class="aq_agenda_col">
                                    <div class="aq_agenda_col_title aq_in">▸ Retornos (recoger / liberar)</div>
                                    <div t-if="!day.retornos.length" class="aq_agenda_empty">—</div>
                                    <t t-foreach="day.retornos" t-as="it" t-key="it.label + it.rep">
                                        <div class="aq_agenda_item" t-on-click="() => this.agendaOpen(it.rep)">
                                            <span class="aq_agenda_qty" t-esc="it.label"/>
                                            <span class="aq_agenda_partner" t-if="it.partner" t-esc="it.partner"/>
                                            <span class="aq_serial_badge aq_agenda_state" t-esc="it.stateLabel"/>
                                        </div>
                                    </t>
                                </div>
                            </div>
                        </div>
                    </t>
                    <div t-if="!agendaDays.length" class="aq_pb_noresult"><i class="fa fa-calendar-check-o"/><span>No hay movimientos en el periodo seleccionado.</span></div>
                </div>
            </t>

            <!-- ===== Rich tooltip ===== -->
            <div t-if="state.tooltip" class="aq_rental_tooltip" t-attf-style="left:{{state.tooltip.x}}px;top:{{state.tooltip.y}}px;">
                <t t-set="b" t-value="state.tooltip.block"/>
                <div class="aq_tt_head">
                    <span class="aq_tt_folio" t-esc="b.name"/>
                    <span class="aq_serial_badge" t-attf-class="aq_state_{{b._stateKey}}" t-esc="b._stateLabel"/>
                </div>
                <div t-if="b.conflict" class="aq_tt_alert">⚠ Conflicto<t t-if="b._conflictWith"> con <t t-esc="b._conflictWith"/></t></div>
                <div t-if="b._overdueOnly" class="aq_tt_alert">⚠ Retorno atrasado</div>
                <table class="aq_tt_table">
                    <tr t-if="b.partner"><td>Cliente</td><td t-esc="b.partner"/></tr>
                    <tr t-if="b.sale_order"><td>Pedido</td><td t-esc="b.sale_order"/></tr>
                    <tr t-if="b.product_name"><td>Producto</td><td t-esc="b.product_name"/></tr>
                    <tr t-if="b.lot_name"><td>Serie</td><td t-esc="b.lot_name"/></tr>
                    <tr t-if="b._reasonLabel"><td>Motivo</td><td t-esc="b._reasonLabel"/></tr>
                    <tr><td>Estado</td><td t-esc="b._opLabel"/></tr>
                    <tr><td>Bloqueo</td><td t-esc="b._rangeLabel"/></tr>
                    <tr t-if="b._billableLabel"><td>Cobrado</td><td t-esc="b._billableLabel"/></tr>
                    <tr><td>Duración</td><td t-esc="b._durationLabel"/></tr>
                </table>
            </div>

            <!-- ===== Drawer ===== -->
            <div t-if="state.selected" class="aq_reservation_drawer">
                <t t-set="r" t-value="state.selected"/>
                <div class="aq_drawer_header">
                    <div class="aq_drawer_title_row">
                        <span class="aq_drawer_title" t-esc="r.name"/>
                        <button class="btn btn-sm btn-light" t-on-click="() => this.closePanel()" aria-label="Cerrar"><i class="fa fa-times"/></button>
                    </div>
                    <span class="aq_serial_badge aq_drawer_badge" t-attf-class="aq_state_{{r._stateKey}}" t-esc="r._stateLabel"/>
                    <div t-if="r.conflict" class="aq_drawer_alert">⚠ Conflicto<t t-if="r._conflictWith"> con <t t-esc="r._conflictWith"/></t></div>
                    <div t-if="r._overdueOnly" class="aq_drawer_alert">⚠ Retorno atrasado</div>
                </div>
                <div class="aq_drawer_body">
                    <div t-if="r.partner" class="aq_drawer_section">
                        <div class="aq_drawer_label">Cliente</div>
                        <div class="aq_drawer_value aq_drawer_customer" t-esc="r.partner"/>
                        <div t-if="r.sale_order" class="aq_drawer_link" t-on-click="() => this.openSaleOrder(r)">Pedido <t t-esc="r.sale_order"/></div>
                    </div>
                    <div class="aq_drawer_section">
                        <div class="aq_drawer_label">Producto</div>
                        <div class="aq_drawer_value" t-esc="r.product_name"/>
                        <div class="aq_drawer_label mt-2">Serie</div>
                        <div class="aq_drawer_value" t-esc="r.lot_name"/>
                    </div>
                    <div t-if="r._billableLabel" class="aq_drawer_section">
                        <div class="aq_drawer_label">Periodo cobrado</div>
                        <div class="aq_drawer_value" t-esc="r._billableLabel"/>
                    </div>
                    <div class="aq_drawer_section">
                        <div class="aq_drawer_label">Bloqueo operativo</div>
                        <div class="aq_drawer_value" t-esc="r._rangeLabel"/>
                        <div class="aq_drawer_duration" t-esc="r._durationLabel"/>
                    </div>
                    <div class="aq_drawer_section">
                        <div class="aq_drawer_label">Estado operativo</div>
                        <div class="aq_drawer_value" t-esc="r._opLabel"/>
                    </div>
                </div>
                <div class="aq_drawer_actions">
                    <button class="btn btn-primary btn-sm" t-on-click="() => this.openReservation(r)">Abrir reserva</button>
                    <button class="btn btn-secondary btn-sm" t-if="r._hasSaleOrder" t-on-click="() => this.openSaleOrder(r)">Abrir pedido</button>
                    <button class="btn btn-outline-danger btn-sm" t-if="r.conflict" t-on-click="() => this.viewConflict(r)">Ver conflicto</button>
                    <button class="btn btn-outline-success btn-sm" t-if="r.type !== 'downtime'" t-on-click="() => this.releaseReservation(r)">Liberar</button>
                </div>
            </div>

            <!-- ===== Downtime quick form ===== -->
            <div t-if="state.showDowntime" class="aq_reservation_drawer aq_dtform">
                <div class="aq_drawer_header">
                    <div class="aq_drawer_title_row">
                        <span class="aq_drawer_title">Nuevo bloqueo</span>
                        <button class="btn btn-sm btn-light" t-on-click="() => state.showDowntime = false" aria-label="Cerrar"><i class="fa fa-times"/></button>
                    </div>
                </div>
                <div class="aq_drawer_body">
                    <div class="aq_drawer_section">
                        <div class="aq_drawer_label">Motivo</div>
                        <select class="o_input" t-model="state.downtimeForm.reason">
                            <option value="maintenance">Mantenimiento</option>
                            <option value="cleaning">Limpieza</option>
                            <option value="repair">Reparación</option>
                            <option value="damaged">Dañado</option>
                            <option value="lost">Perdido</option>
                            <option value="internal_use">Uso interno</option>
                            <option value="other">Otro</option>
                        </select>
                        <div class="aq_drawer_label mt-2">Inicio</div>
                        <input type="datetime-local" class="o_input" t-model="state.downtimeForm.start"/>
                        <div class="aq_drawer_label mt-2">Fin (opcional)</div>
                        <input type="datetime-local" class="o_input" t-model="state.downtimeForm.end"/>
                    </div>
                </div>
                <div class="aq_drawer_actions">
                    <button class="btn btn-primary btn-sm" t-on-click="() => this.submitDowntime()">Crear bloqueo</button>
                </div>
            </div>
        </div>
    </t>

    <!-- Reusable reservation block (used by timeline & customer modes) -->
    <t t-name="aq_rental_serial_planning.Block">
        <div t-att-class="blockClass(block)" t-att-style="block._style"
             t-att-title="block._stateLabel + ' · ' + block.name"
             t-att-aria-label="block._stateLabel + ' ' + block.name + (block.partner ? ' ' + block.partner : '')"
             tabindex="0"
             t-on-click.stop="() => this.onBlockClick(block)"
             t-on-mouseenter="(ev) => this.onBlockEnter(ev, block)"
             t-on-mouseleave="() => this.onBlockLeave()">
            <div class="aq_block_billable" t-if="block._billableStyle" t-att-style="block._billableStyle"/>
            <span class="aq_block_conflict_icon" t-if="block.conflict"><i class="fa fa-exclamation-triangle"/></span>
            <span class="aq_block_overdue_icon" t-if="block._overdueOnly"><i class="fa fa-clock-o"/></span>
            <div class="aq_block_customer" t-if="block.partner" t-esc="block.partner"/>
            <div class="aq_block_main"><span t-esc="block.name"/> · <span t-esc="block._stateLabel"/></div>
            <div class="aq_block_dates" t-esc="block._rangeLabel"/>
        </div>
    </t>
</templates>
```

## ./tests/__init__.py
```py
from . import test_serial_reservation
from . import test_availability
from . import test_package
```

## ./tests/test_availability.py
```py
# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["rental.availability.service"]
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create({
            "name": "Sillas Manhattan",
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
        })
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"SILLA-{i:03d}", "product_id": cls.product.id}
            for i in range(1, 21)
        ])
        # Put one physical unit per serial in stock.
        for lot in cls.lots:
            cls.env["stock.quant"].create({
                "product_id": cls.product.id,
                "lot_id": lot.id,
                "location_id": cls.stock_loc.id,
                "quantity": 1.0,
            })
        cls.partner = cls.env["res.partner"].create({"name": "Event Co"})
        cls.start = datetime(2026, 8, 6, 8, 0)   # Thursday
        cls.end = datetime(2026, 8, 11, 18, 0)   # Tuesday

    def test_all_available_initially(self):
        data = self.service.get_product_availability(
            self.product.id, self.start, self.end)
        self.assertEqual(data["total_serials"], 20)
        self.assertEqual(data["available_count"], 20)

    def test_partial_reservation_keeps_rest_available(self):
        """Case 1: reserve 5 serials, 15 remain available in the period."""
        for lot in self.lots[:5]:
            self.env["rental.serial.reservation"].create({
                "product_id": self.product.id,
                "lot_id": lot.id,
                "partner_id": self.partner.id,
                "reservation_block_start": self.start,
                "reservation_block_end": self.end,
                "state": "reserved",
            })
        data = self.service.get_product_availability(
            self.product.id, self.start, self.end)
        self.assertEqual(data["available_count"], 15)
        self.assertEqual(data["reserved_count"], 5)

    def test_downtime_blocks_serial(self):
        """Case 6: a serial in maintenance is not available."""
        self.env["rental.serial.downtime"].create({
            "lot_id": self.lots[9].id,
            "reason": "maintenance",
            "start_datetime": datetime(2026, 8, 3, 0, 0),
            "end_datetime": datetime(2026, 8, 5, 0, 0),
        })
        data = self.service.get_product_availability(
            self.product.id,
            datetime(2026, 8, 4, 0, 0), datetime(2026, 8, 4, 12, 0))
        self.assertNotIn(self.lots[9].id, data["available_serials"])
        self.assertIn(self.lots[9].id, data["unavailable_serials"])

    def test_billable_vs_block_period(self):
        """Case 2: blocking is computed on the operational period, not billable."""
        # Reservation blocks Thu-Tue although billable is Saturday only.
        self.env["rental.serial.reservation"].create({
            "product_id": self.product.id,
            "lot_id": self.lots[0].id,
            "partner_id": self.partner.id,
            "rental_billable_start": datetime(2026, 8, 8, 10, 0),
            "rental_billable_end": datetime(2026, 8, 8, 23, 59),
            "reservation_block_start": self.start,
            "reservation_block_end": self.end,
            "state": "reserved",
        })
        # Querying Thursday (outside billable but inside block) -> unavailable.
        avail = self.service.get_available_serials(
            self.product.id,
            datetime(2026, 8, 6, 9, 0), datetime(2026, 8, 6, 12, 0))
        self.assertNotIn(self.lots[0], avail)
```

## ./tests/test_package.py
```py
# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestPackageAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["rental.availability.service"]
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")

        cls.chair = cls._make_serial_product("Sillas Manhattan", 20)
        cls.table = cls._make_serial_product("Mesa Banquete", 3)

        cls.package = cls.env["rental.package.template"].create({
            "name": "Paquete Evento A",
            "line_ids": [
                (0, 0, {"product_id": cls.chair.id, "quantity": 5, "required": True}),
                (0, 0, {"product_id": cls.table.id, "quantity": 1, "required": True}),
            ],
        })
        cls.start = datetime(2026, 8, 6, 8, 0)
        cls.end = datetime(2026, 8, 11, 18, 0)

    @classmethod
    def _make_serial_product(cls, name, qty):
        product = cls.env["product.product"].create({
            "name": name,
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
            "x_rental_package_eligible": True,
        })
        lots = cls.env["stock.lot"].create([
            {"name": f"{name[:5].upper()}-{i:03d}", "product_id": product.id}
            for i in range(1, qty + 1)
        ])
        for lot in lots:
            cls.env["stock.quant"].create({
                "product_id": product.id,
                "lot_id": lot.id,
                "location_id": cls.stock_loc.id,
                "quantity": 1.0,
            })
        return product

    def test_package_limited_by_scarcest_component(self):
        """Case 3: min(20/5, 3/1) = 3 packages; tables are the limiter."""
        data = self.service.get_package_availability(
            self.package.id, self.start, self.end)
        self.assertEqual(data["max_packages"], 3)
        limiting = [l for l in data["lines"] if l["is_limiting"]]
        limiting_products = {l["product_id"] for l in limiting}
        self.assertIn(self.table.id, limiting_products)
        self.assertNotIn(self.chair.id, limiting_products)
```

## ./tests/test_serial_reservation.py
```py
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError


class TestSerialReservation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["rental.serial.reservation"]
        cls.product = cls.env["product.product"].create({
            "name": "Sillas Manhattan",
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
            "x_requires_serial_reservation": True,
        })
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"SILLA-{i:03d}", "product_id": cls.product.id}
            for i in range(1, 6)
        ])
        cls.partner = cls.env["res.partner"].create({"name": "Event Co"})

    def _reservation(self, lot, start, end, state="reserved"):
        return self.Reservation.create({
            "product_id": self.product.id,
            "lot_id": lot.id,
            "partner_id": self.partner.id,
            "reservation_block_start": start,
            "reservation_block_end": end,
            "state": state,
        })

    def test_block_period_validation(self):
        start = datetime(2026, 7, 1, 10, 0)
        with self.assertRaises(Exception):
            self._reservation(self.lots[0], start, start - timedelta(hours=1))

    def test_overlap_same_serial_blocked(self):
        """Case: no double booking of the same serial on overlapping periods."""
        s1 = datetime(2026, 7, 2, 8, 0)
        e1 = datetime(2026, 7, 6, 18, 0)
        self._reservation(self.lots[0], s1, e1)
        with self.assertRaises(ValidationError):
            self._reservation(self.lots[0],
                              datetime(2026, 7, 4, 8, 0),
                              datetime(2026, 7, 8, 18, 0))

    def test_non_overlap_same_serial_ok(self):
        self._reservation(self.lots[0],
                          datetime(2026, 7, 2, 8, 0),
                          datetime(2026, 7, 6, 18, 0))
        # Touching at the boundary is allowed ([) semantics).
        r2 = self._reservation(self.lots[0],
                               datetime(2026, 7, 6, 18, 0),
                               datetime(2026, 7, 9, 18, 0))
        self.assertEqual(r2.conflict_status, "ok")

    def test_released_does_not_block(self):
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.write({"state": "released", "actual_return_datetime": datetime(2026, 7, 6)})
        # Same period now free for a new reservation.
        r2 = self._reservation(self.lots[0],
                               datetime(2026, 7, 3, 8, 0),
                               datetime(2026, 7, 5, 18, 0))
        self.assertEqual(r2.conflict_status, "ok")

    def test_change_serial(self):
        """Case 4: change of serial validates availability and frees the old one."""
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.action_change_serial(self.lots[1].id)
        self.assertEqual(r1.lot_id, self.lots[1])

    def test_release_requires_return_when_policy(self):
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.auto_release_policy = "on_return_validation"
        with self.assertRaises(UserError):
            r1.action_release()
        r1.action_return()
        r1.action_release()
        self.assertEqual(r1.state, "released")
```

## ./views/product_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_product_template_form_serial_planning" model="ir.ui.view">
        <field name="name">product.template.form.serial.planning</field>
        <field name="model">product.template</field>
        <field name="inherit_id" ref="product.product_template_only_form_view"/>
        <field name="arch" type="xml">
            <xpath expr="//notebook" position="inside">
                <page string="Planeación por serie" name="serial_planning"
                      invisible="not rent_ok and not x_rental_serial_planning">
                    <group>
                        <group string="Planeación">
                            <field name="x_rental_serial_planning"/>
                            <field name="x_requires_serial_reservation"/>
                            <field name="x_rental_package_eligible"/>
                            <field name="x_allow_auto_serial_assignment"/>
                            <field name="x_allow_manual_serial_assignment"/>
                        </group>
                        <group string="Márgenes operativos (horas)">
                            <field name="x_default_preparation_hours"/>
                            <field name="x_default_delivery_buffer_hours"/>
                            <field name="x_default_return_buffer_hours"/>
                            <field name="x_default_cleaning_hours"/>
                        </group>
                    </group>
                    <div class="text-muted">
                        El periodo operativo de bloqueo se deriva del periodo
                        facturable ensanchándolo con estos márgenes
                        (preparación + entrega antes, retorno + limpieza después).
                    </div>
                </page>
            </xpath>
        </field>
    </record>

    <record id="view_product_product_form_serial_planning" model="ir.ui.view">
        <field name="name">product.product.form.serial.planning</field>
        <field name="model">product.product</field>
        <field name="inherit_id" ref="product.product_normal_form_view"/>
        <field name="arch" type="xml">
            <xpath expr="//div[@name='button_box']" position="inside">
                <button name="action_open_serial_availability" type="object"
                        class="oe_stat_button" icon="fa-calendar"
                        invisible="tracking != 'serial'">
                    <field name="x_serial_reservation_count" widget="statinfo"
                           string="Reservas"/>
                </button>
            </xpath>
        </field>
    </record>
</odoo>
```

## ./views/rental_package_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_rental_package_list" model="ir.ui.view">
        <field name="name">rental.package.template.list</field>
        <field name="model">rental.package.template</field>
        <field name="arch" type="xml">
            <list>
                <field name="name"/>
                <field name="code"/>
                <field name="component_count"/>
                <field name="pricing_policy"/>
                <field name="company_id" groups="base.group_multi_company"/>
            </list>
        </field>
    </record>

    <record id="view_rental_package_form" model="ir.ui.view">
        <field name="name">rental.package.template.form</field>
        <field name="model">rental.package.template</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_check_availability" type="object"
                            string="Ver disponibilidad" class="btn-primary"/>
                </header>
                <sheet>
                    <div class="oe_button_box" name="button_box">
                        <button name="action_check_availability" type="object"
                                class="oe_stat_button" icon="fa-calendar-check-o">
                            <field name="component_count" widget="statinfo" string="Componentes"/>
                        </button>
                    </div>
                    <div class="oe_title">
                        <label for="name"/>
                        <h1><field name="name" placeholder="Nombre del paquete"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="code"/>
                            <field name="sale_product_id"/>
                            <field name="active" widget="boolean_toggle"/>
                        </group>
                        <group>
                            <field name="pricing_policy"/>
                            <field name="fixed_price"
                                   invisible="pricing_policy != 'fixed_package_price'"/>
                            <field name="currency_id" invisible="1"/>
                            <field name="hide_components_on_quote"/>
                            <field name="hide_components_on_invoice"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Componentes" name="components">
                            <field name="line_ids">
                                <list editable="bottom">
                                    <field name="sequence" widget="handle"/>
                                    <field name="product_id"/>
                                    <field name="tracking"/>
                                    <field name="quantity"/>
                                    <field name="required"/>
                                    <field name="allow_substitution"/>
                                    <field name="allowed_substitute_product_ids"
                                           widget="many2many_tags"
                                           column_invisible="not parent.id"
                                           invisible="not allow_substitution"/>
                                    <field name="discount_percentage"/>
                                    <field name="notes"/>
                                </list>
                            </field>
                        </page>
                        <page string="Descripción" name="desc">
                            <field name="description"/>
                        </page>
                    </notebook>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_rental_package" model="ir.actions.act_window">
        <field name="name">Paquetes de renta</field>
        <field name="res_model">rental.package.template</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

## ./views/rental_planning_board_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_rental_planning_board" model="ir.actions.client">
        <field name="name">Tablero de Planeación</field>
        <field name="tag">aq_rental_planning_board</field>
    </record>

    <record id="action_rental_kpi_dashboard" model="ir.actions.client">
        <field name="name">Indicadores de Planeación</field>
        <field name="tag">aq_rental_kpi_dashboard</field>
    </record>
</odoo>
```

## ./views/rental_planning_menus.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_rental_planning_root" name="Planeación"
              web_icon="aq_rental_serial_planning,static/description/icon.png"
              sequence="40"
              groups="group_rental_planner_user"/>

    <menuitem id="menu_rental_kpi_dashboard" name="Indicadores"
              parent="menu_rental_planning_root"
              action="action_rental_kpi_dashboard" sequence="5"/>

    <menuitem id="menu_rental_planning_board" name="Tablero"
              parent="menu_rental_planning_root"
              action="action_rental_planning_board" sequence="10"/>

    <menuitem id="menu_rental_reservations" name="Reservas por Serie"
              parent="menu_rental_planning_root"
              action="action_rental_serial_reservation" sequence="20"/>

    <menuitem id="menu_rental_downtime" name="Mantenimiento / Bloqueos"
              parent="menu_rental_planning_root"
              action="action_rental_downtime" sequence="30"
              groups="group_rental_warehouse_user"/>

    <menuitem id="menu_rental_config" name="Configuración"
              parent="menu_rental_planning_root" sequence="90"
              groups="group_rental_administrator"/>

    <menuitem id="menu_rental_packages" name="Paquetes"
              parent="menu_rental_config"
              action="action_rental_package" sequence="10"/>

    <menuitem id="menu_rental_sample_data" name="Cargar datos de ejemplo"
              parent="menu_rental_config"
              action="action_rental_sample_data" sequence="90"
              groups="group_rental_administrator"/>
</odoo>
```

## ./views/rental_serial_downtime_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_rental_downtime_list" model="ir.ui.view">
        <field name="name">rental.serial.downtime.list</field>
        <field name="model">rental.serial.downtime</field>
        <field name="arch" type="xml">
            <list decoration-muted="state in ('done','cancelled')"
                  decoration-danger="reason in ('damaged','lost')">
                <field name="name"/>
                <field name="lot_id"/>
                <field name="product_id"/>
                <field name="reason"/>
                <field name="start_datetime"/>
                <field name="end_datetime"/>
                <field name="state" widget="badge"/>
            </list>
        </field>
    </record>

    <record id="view_rental_downtime_form" model="ir.ui.view">
        <field name="name">rental.serial.downtime.form</field>
        <field name="model">rental.serial.downtime</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_start" type="object" string="Iniciar"
                            invisible="state != 'scheduled'"/>
                    <button name="action_done" type="object" string="Marcar terminado"
                            class="btn-primary" invisible="state not in ('scheduled','in_progress')"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            invisible="state in ('done','cancelled')"/>
                    <field name="state" widget="statusbar"/>
                </header>
                <sheet>
                    <div class="oe_title"><h1><field name="name" readonly="1"/></h1></div>
                    <group>
                        <group>
                            <field name="lot_id"/>
                            <field name="product_id"/>
                            <field name="reason"/>
                        </group>
                        <group>
                            <field name="start_datetime"/>
                            <field name="end_datetime"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                        </group>
                    </group>
                    <field name="notes" placeholder="Notas..."/>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="view_rental_downtime_calendar" model="ir.ui.view">
        <field name="name">rental.serial.downtime.calendar</field>
        <field name="model">rental.serial.downtime</field>
        <field name="arch" type="xml">
            <calendar date_start="start_datetime" date_stop="end_datetime"
                      color="reason" mode="month">
                <field name="lot_id"/>
                <field name="reason"/>
            </calendar>
        </field>
    </record>

    <record id="action_rental_downtime" model="ir.actions.act_window">
        <field name="name">Mantenimiento / Bloqueos</field>
        <field name="res_model">rental.serial.downtime</field>
        <field name="view_mode">list,form,calendar</field>
    </record>
</odoo>
```

## ./views/rental_serial_reservation_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- LIST -->
    <record id="view_rental_serial_reservation_list" model="ir.ui.view">
        <field name="name">rental.serial.reservation.list</field>
        <field name="model">rental.serial.reservation</field>
        <field name="arch" type="xml">
            <list decoration-danger="conflict_status == 'conflict'"
                  decoration-warning="is_overdue"
                  decoration-muted="state in ('released','cancelled')">
                <field name="name"/>
                <field name="product_id"/>
                <field name="lot_id"/>
                <field name="partner_id"/>
                <field name="reservation_block_start"/>
                <field name="reservation_block_end"/>
                <field name="rental_billable_start" optional="hide"/>
                <field name="rental_billable_end" optional="hide"/>
                <field name="state" widget="badge"
                       decoration-success="state in ('released',)"
                       decoration-info="state in ('reserved','prepared')"
                       decoration-warning="state in ('soft_hold','in_use','delivered')"/>
                <field name="conflict_status" widget="badge"
                       decoration-danger="conflict_status == 'conflict'"/>
                <field name="is_overdue" optional="show"/>
                <field name="company_id" groups="base.group_multi_company" optional="hide"/>
            </list>
        </field>
    </record>

    <!-- FORM -->
    <record id="view_rental_serial_reservation_form" model="ir.ui.view">
        <field name="name">rental.serial.reservation.form</field>
        <field name="model">rental.serial.reservation</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_soft_hold" type="object" string="Apartar"
                            invisible="state not in ('draft','quotation')"/>
                    <button name="action_reserve" type="object" string="Reservar"
                            class="btn-primary"
                            invisible="state not in ('draft','quotation','soft_hold')"/>
                    <button name="action_prepare" type="object" string="Preparar"
                            invisible="state != 'reserved'"/>
                    <button name="action_pickup" type="object" string="Retirar"
                            invisible="state != 'prepared'"/>
                    <button name="action_deliver" type="object" string="Entregar"
                            invisible="state != 'picked_up'"/>
                    <button name="action_set_in_use" type="object" string="Marcar en uso"
                            invisible="state != 'delivered'"/>
                    <button name="action_create_delivery_picking" type="object"
                            string="Crear entrega" class="btn-primary"
                            groups="aq_rental_serial_planning.group_rental_warehouse_user"
                            invisible="state not in ('reserved','prepared','picked_up') or lot_id == False"/>
                    <button name="action_return" type="object" string="Registrar devolución"
                            invisible="state not in ('delivered','in_use','picked_up')"/>
                    <button name="action_create_return_picking" type="object"
                            string="Crear retorno"
                            groups="aq_rental_serial_planning.group_rental_warehouse_user"
                            invisible="state not in ('delivered','in_use') or lot_id == False"/>
                    <button name="action_release" type="object" string="Liberar"
                            class="btn-primary"
                            groups="aq_rental_serial_planning.group_rental_planner_manager"
                            invisible="state in ('released','cancelled','draft')"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            invisible="state in ('released','cancelled')"/>
                    <button name="action_reset_to_draft" type="object" string="Restablecer a borrador"
                            invisible="state not in ('cancelled',)"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,reserved,prepared,delivered,in_use,returned,released"/>
                </header>
                <sheet>
                    <widget name="web_ribbon" title="Conflicto" bg_color="text-bg-danger"
                            invisible="conflict_status != 'conflict'"/>
                    <widget name="web_ribbon" title="Atrasado" bg_color="text-bg-warning"
                            invisible="not is_overdue"/>
                    <div class="oe_title">
                        <h1><field name="name" readonly="1"/></h1>
                    </div>
                    <group>
                        <group string="Inventario">
                            <field name="product_id"/>
                            <field name="lot_id"/>
                            <field name="quantity"/>
                            <field name="warehouse_id"/>
                            <field name="location_id"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                        </group>
                        <group string="Comercial">
                            <field name="partner_id"/>
                            <field name="sale_order_id"/>
                            <field name="sale_order_line_id" invisible="1"/>
                            <field name="package_id"/>
                        </group>
                    </group>
                    <group>
                        <group string="Periodo facturable (lo que se cobra)">
                            <field name="rental_billable_start"/>
                            <field name="rental_billable_end"/>
                        </group>
                        <group string="Periodo operativo (lo que bloquea stock)">
                            <field name="reservation_block_start"/>
                            <field name="reservation_block_end"/>
                            <field name="auto_release_policy"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Operaciones" name="ops">
                            <group>
                                <group string="Marcas reales">
                                    <field name="actual_pickup_datetime"/>
                                    <field name="actual_delivery_datetime"/>
                                    <field name="actual_return_datetime"/>
                                    <field name="actual_release_datetime"/>
                                    <field name="delivery_picking_id"/>
                                    <field name="return_picking_id"/>
                                </group>
                                <group string="Apartado temporal">
                                    <field name="soft_hold_until"/>
                                    <field name="soft_hold_owner_id"/>
                                    <field name="soft_hold_reason"/>
                                </group>
                            </group>
                            <field name="notes" placeholder="Notas..."/>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <!-- SEARCH -->
    <record id="view_rental_serial_reservation_search" model="ir.ui.view">
        <field name="name">rental.serial.reservation.search</field>
        <field name="model">rental.serial.reservation</field>
        <field name="arch" type="xml">
            <search>
                <field name="name" string="Referencia"/>
                <field name="product_id"/>
                <field name="lot_id"/>
                <field name="partner_id"/>
                <field name="sale_order_id"/>
                <filter name="conflicts" string="Conflictos"
                        domain="[('conflict_status', '=', 'conflict')]"/>
                <filter name="active_blocks" string="Bloqueos activos"
                        domain="[('state', 'in', ['soft_hold', 'reserved', 'prepared', 'picked_up', 'delivered', 'in_use', 'returned'])]"/>
                <separator/>
                <filter name="soft_hold" string="Apartados" domain="[('state', '=', 'soft_hold')]"/>
                <filter name="released" string="Liberadas" domain="[('state', '=', 'released')]"/>
                <separator/>
                <filter name="g_product" string="Producto" context="{'group_by': 'product_id'}"/>
                <filter name="g_lot" string="Serie" context="{'group_by': 'lot_id'}"/>
                <filter name="g_state" string="Estado" context="{'group_by': 'state'}"/>
                <filter name="g_partner" string="Cliente" context="{'group_by': 'partner_id'}"/>
            </search>
        </field>
    </record>

    <!-- CALENDAR (native fallback, grouped by serial) -->
    <record id="view_rental_serial_reservation_calendar" model="ir.ui.view">
        <field name="name">rental.serial.reservation.calendar</field>
        <field name="model">rental.serial.reservation</field>
        <field name="arch" type="xml">
            <calendar string="Reservas" date_start="reservation_block_start"
                      date_stop="reservation_block_end" color="lot_id" mode="month">
                <field name="lot_id" filters="1"/>
                <field name="product_id" filters="1"/>
                <field name="partner_id"/>
                <field name="state"/>
            </calendar>
        </field>
    </record>

    <record id="action_rental_serial_reservation" model="ir.actions.act_window">
        <field name="name">Reservas por serie</field>
        <field name="res_model">rental.serial.reservation</field>
        <field name="view_mode">list,form,calendar</field>
        <field name="search_view_id" ref="view_rental_serial_reservation_search"/>
    </record>
</odoo>
```

## ./views/sale_order_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_order_form_serial_planning" model="ir.ui.view">
        <field name="name">sale.order.form.serial.planning</field>
        <field name="model">sale.order</field>
        <field name="inherit_id" ref="sale.view_order_form"/>
        <field name="arch" type="xml">
            <!-- Smart buttons -->
            <xpath expr="//div[@name='button_box']" position="inside">
                <button name="action_view_serial_reservations" type="object"
                        class="oe_stat_button" icon="fa-barcode"
                        invisible="x_reservation_count == 0">
                    <field name="x_reservation_count" widget="statinfo" string="Series"/>
                </button>
                <button name="action_view_serial_pickings" type="object"
                        class="oe_stat_button" icon="fa-truck"
                        invisible="x_serial_picking_count == 0">
                    <field name="x_serial_picking_count" widget="statinfo" string="Transferencias"/>
                </button>
            </xpath>

            <!-- Event header toggle -->
            <xpath expr="//field[@name='partner_id']" position="after">
                <field name="x_is_event_rental"/>
            </xpath>

            <!-- Header actions -->
            <xpath expr="//header" position="inside">
                <button name="action_explode_packages" type="object"
                        string="Explotar paquetes" invisible="not x_is_event_rental"/>
                <button name="action_open_planning_board" type="object"
                        string="Tablero de Planeación" invisible="not x_is_event_rental"/>
            </xpath>

            <!-- Order line columns -->
            <xpath expr="//field[@name='order_line']/list/field[@name='product_uom_qty']" position="after">
                <field name="x_requires_serial_assignment" column_invisible="1"/>
                <field name="x_reserved_serial_count" string="Series"
                       invisible="not x_requires_serial_assignment"/>
                <field name="x_available_qty_for_period" string="Disp."
                       invisible="not x_requires_serial_assignment"/>
                <field name="x_conflict_warning" class="text-danger"
                       invisible="not x_conflict_warning"/>
                <button name="action_auto_assign_serials" type="object"
                        string="Auto" icon="fa-magic"
                        invisible="not x_requires_serial_assignment"/>
                <button name="action_open_manual_assign" type="object"
                        string="Asignar" icon="fa-barcode"
                        invisible="not x_requires_serial_assignment"/>
            </xpath>

            <!-- Event & periods page -->
            <xpath expr="//notebook" position="inside">
                <page string="Evento y Periodos" name="event_periods"
                      invisible="not x_is_event_rental">
                    <group>
                        <group string="Evento">
                            <field name="x_event_name"/>
                            <field name="x_event_location"/>
                            <field name="x_event_start"/>
                            <field name="x_event_end"/>
                        </group>
                        <group string="Periodos">
                            <label for="x_billable_start" string="Periodo facturable"/>
                            <div class="o_row">
                                <field name="x_billable_start" nolabel="1"/>
                                <span class="mx-2">→</span>
                                <field name="x_billable_end" nolabel="1"/>
                            </div>
                            <label for="x_block_start" string="Periodo operativo"/>
                            <div class="o_row">
                                <field name="x_block_start" nolabel="1"/>
                                <span class="mx-2">→</span>
                                <field name="x_block_end" nolabel="1"/>
                            </div>
                            <field name="x_reservation_conflict_count"
                                   invisible="x_reservation_conflict_count == 0"
                                   class="text-danger"/>
                        </group>
                    </group>
                    <field name="x_logistics_notes" placeholder="Notas logísticas..."/>
                </page>
            </xpath>

            <!-- Notebook page with reservations -->
            <xpath expr="//notebook" position="inside">
                <page string="Reservas por serie" name="serial_reservations"
                      invisible="x_reservation_count == 0">
                    <field name="x_reservation_ids" readonly="1">
                        <list decoration-danger="conflict_status == 'conflict'">
                            <field name="product_id"/>
                            <field name="lot_id"/>
                            <field name="reservation_block_start"/>
                            <field name="reservation_block_end"/>
                            <field name="state" widget="badge"/>
                            <field name="conflict_status"/>
                        </list>
                    </field>
                </page>
            </xpath>
        </field>
    </record>
</odoo>
```

## ./views/stock_lot_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_stock_lot_form_serial_planning" model="ir.ui.view">
        <field name="name">stock.lot.form.serial.planning</field>
        <field name="model">stock.lot</field>
        <field name="inherit_id" ref="stock.view_production_lot_form"/>
        <field name="arch" type="xml">
            <xpath expr="//div[@name='button_box']" position="inside">
                <button name="action_view_reservations" type="object"
                        class="oe_stat_button" icon="fa-calendar">
                    <field name="x_reservation_count" widget="statinfo" string="Reservas"/>
                </button>
            </xpath>
            <xpath expr="//field[@name='product_id']" position="after">
                <field name="x_currency_id" invisible="1"/>
                <field name="x_rental_revenue" widget="monetary"/>
                <field name="x_downtime_count"/>
            </xpath>
        </field>
    </record>
</odoo>
```

## ./wizard/__init__.py
```py
from . import rental_serial_assign_wizard
from . import rental_sample_data
```

## ./wizard/rental_sample_data_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_rental_sample_data_wizard_form" model="ir.ui.view">
        <field name="name">rental.sample.data.wizard.form</field>
        <field name="model">rental.sample.data.wizard</field>
        <field name="arch" type="xml">
            <form string="Cargar datos de ejemplo">
                <div class="oe_title">
                    <h2>Cargar datos de ejemplo de renta</h2>
                </div>
                <p>
                    Se creará un conjunto completo y realista para probar el módulo:
                </p>
                <ul>
                    <li>10 productos serializados con stock (sillas, mesas, bocinas, luces, carpa, etc.).</li>
                    <li>5 clientes de evento.</li>
                    <li>3 paquetes (suma, precio fijo y con descuentos) con sustitución.</li>
                    <li>Órdenes de evento con periodo facturable y operativo.</li>
                    <li>Reservas de serial en todos los estados, soft holds y downtime.</li>
                    <li>Pedidos confirmados con fechas escalonadas y transferencias reales de salida/retorno.</li>
                </ul>
                <p class="text-muted">
                    Las fechas son relativas a hoy, así que el Tablero de Planeación
                    aparecerá poblado de inmediato. Solo puede ejecutarse una vez.
                </p>
                <footer>
                    <button name="action_load" type="object" string="Cargar datos de ejemplo"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_rental_sample_data" model="ir.actions.act_window">
        <field name="name">Cargar datos de ejemplo</field>
        <field name="res_model">rental.sample.data.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
</odoo>
```

## ./wizard/rental_sample_data.py
```py
# -*- coding: utf-8 -*-
"""On-demand sample data loader.

Odoo only loads ``demo/`` files when the database was created *with
demonstration data*. On production/QA databases created without it, this
wizard lets an administrator populate a full, realistic dataset on demand
(products + serials + stock, customers, packages, event orders, reservations
in every state, downtime, and confirmed orders with real serial pickings).

Idempotent: it refuses to run twice (marker product check).
"""
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# key, name, n_serials, default_code, price, (prep, deliv, ret, clean), requires_serial
_PRODUCTS = [
    ("chair", "Sillas Manhattan", 20, "AQ-SILLA", 45.0, (4, 12, 12, 6), True),
    ("table", "Mesa Banquete Redonda", 8, "AQ-MESA", 120.0, (4, 12, 12, 8), True),
    ("speaker", "Bocina JBL EON 715", 6, "AQ-BOC", 260.0, (2, 6, 6, 4), True),
    ("light", "Luz PAR LED RGB", 12, "AQ-PAR", 80.0, (2, 6, 6, 3), True),
    ("tent", "Carpa 6x6 Cristal", 3, "AQ-CARPA", 1500.0, (24, 24, 24, 24), True),
    ("projector", "Proyector Epson 5000L", 4, "AQ-PROY", 450.0, (3, 6, 6, 4), True),
    ("screen", "Pantalla Proyección 120in", 4, "AQ-PANT", 180.0, (3, 6, 6, 2), True),
    ("floor", "Pista de Baile Módulo", 10, "AQ-PISTA", 150.0, (8, 12, 12, 10), True),
    ("heater", "Calentador de Patio", 5, "AQ-CALEN", 140.0, (2, 6, 6, 4), True),
    ("mic", "Micrófono Inalámbrico Shure", 8, "AQ-MIC", 90.0, (1, 4, 4, 2), True),
]

_PARTNERS = [
    ("aurora", "Bodas Aurora", "contacto@bodasaurora.mx"),
    ("zenith", "Corporativo Zenith", "eventos@zenith.com"),
    ("luna", "Eventos Luna", "hola@eventosluna.mx"),
    ("granvia", "Hotel Gran Vía", "banquetes@granvia.mx"),
    ("cumbre", "Productora Cumbre", "produccion@cumbre.tv"),
]


class RentalSampleDataWizard(models.TransientModel):
    _name = "rental.sample.data.wizard"
    _description = "Cargar datos de ejemplo de renta"

    @api.model
    def _already_loaded(self):
        return bool(self.env["product.product"].search_count(
            [("default_code", "=", "AQ-SILLA")]))

    @api.model
    def _load_sample_data_auto(self):
        """Idempotently create the sample dataset.

        Called from a ``<function>`` data tag so it runs on EVERY install and
        update, regardless of the database demo flag. Must never raise: a
        failure here cannot be allowed to abort module loading.
        """
        if self._already_loaded():
            return
        try:
            with self.env.cr.savepoint():
                self._create_all()
            _logger.info("AQ Rental: datos de ejemplo creados automáticamente.")
        except Exception:
            _logger.exception(
                "AQ Rental: fallo al crear los datos de ejemplo automáticos.")

    def action_load(self):
        self.ensure_one()
        if self._already_loaded():
            raise UserError(_(
                "Los datos de ejemplo ya fueron cargados anteriormente."))
        self._create_all()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Datos de ejemplo cargados"),
                "message": _("Catálogo, clientes, paquetes, órdenes, reservas, "
                             "downtime y pedidos confirmados con transferencias "
                             "fueron creados. Abre el Tablero de Planeación."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    # ------------------------------------------------------------------
    @api.model
    def _at(self, day, hour):
        return (datetime.now() + timedelta(days=day)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

    def _create_all(self):
        company = self.env.company
        stock_loc = self.env.ref("stock.stock_location_stock")
        Product = self.env["product.product"]
        Lot = self.env["stock.lot"]
        Quant = self.env["stock.quant"]

        categ = self.env["product.category"].create({"name": "Renta de Eventos"})

        # --- Products + serials + stock ---
        products = {}
        serials = {}
        for key, name, n, code, price, buf, req in _PRODUCTS:
            pre, deliv, ret, clean = buf
            product = Product.create({
                "name": name,
                "default_code": code,
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
                "rent_ok": True,
                "list_price": price,
                "categ_id": categ.id,
                "x_rental_serial_planning": True,
                "x_requires_serial_reservation": req,
                "x_rental_package_eligible": True,
                "x_default_preparation_hours": pre,
                "x_default_delivery_buffer_hours": deliv,
                "x_default_return_buffer_hours": ret,
                "x_default_cleaning_hours": clean,
            })
            products[key] = product
            lots = Lot.create([
                {"name": "%s-%03d" % (code.replace("AQ-", ""), i),
                 "product_id": product.id, "company_id": company.id}
                for i in range(1, n + 1)])
            serials[key] = lots
            Quant.create([
                {"product_id": product.id, "lot_id": lot.id,
                 "location_id": stock_loc.id, "quantity": 1.0}
                for lot in lots])

        # Non-serial consumables (package substitution demo)
        linen = Product.create({
            "name": "Mantel Premium Blanco", "default_code": "AQ-MANTEL-B",
            "type": "consu", "is_storable": True, "rent_ok": True,
            "list_price": 25.0, "categ_id": categ.id,
            "x_rental_package_eligible": True})
        linen_alt = Product.create({
            "name": "Mantel Premium Negro", "default_code": "AQ-MANTEL-N",
            "type": "consu", "is_storable": True, "rent_ok": True,
            "list_price": 25.0, "categ_id": categ.id,
            "x_rental_package_eligible": True})

        # --- Partners ---
        partners = {}
        for key, name, email in _PARTNERS:
            partners[key] = self.env["res.partner"].create({
                "name": name, "email": email,
                "is_company": True, "customer_rank": 1})

        # --- Packages ---
        Pkg = self.env["rental.package.template"]
        PkgLine = self.env["rental.package.template.line"]
        boda = Pkg.create({
            "name": "Paquete Boda Premium", "code": "PKG-BODA",
            "pricing_policy": "sum_components",
            "description": "Mobiliario y audio para boda de hasta 100 invitados."})
        for pk, qty, req in [("chair", 10, True), ("table", 2, True),
                             ("speaker", 2, True), ("light", 4, True), ("floor", 1, False)]:
            PkgLine.create({"package_id": boda.id, "product_id": products[pk].id,
                            "quantity": qty, "required": req})
        PkgLine.create({
            "package_id": boda.id, "product_id": linen.id, "quantity": 12,
            "required": True, "allow_substitution": True,
            "allowed_substitute_product_ids": [(6, 0, [linen_alt.id])]})

        conf = Pkg.create({
            "name": "Paquete Conferencia Corporativa", "code": "PKG-CONF",
            "pricing_policy": "fixed_package_price", "fixed_price": 3500.0,
            "hide_components_on_quote": True,
            "description": "Proyección, audio y asientos para conferencia."})
        for pk, qty in [("projector", 1), ("screen", 1), ("speaker", 2),
                        ("mic", 2), ("chair", 15)]:
            PkgLine.create({"package_id": conf.id, "product_id": products[pk].id,
                            "quantity": qty, "required": True})

        terr = Pkg.create({
            "name": "Paquete Terraza Otoño", "code": "PKG-TERR",
            "pricing_policy": "discount_components",
            "description": "Carpa, calefacción y mesas para terraza."})
        for pk, qty, req, disc in [("tent", 1, True, 0), ("heater", 4, True, 10),
                                   ("table", 4, True, 5), ("light", 6, False, 0)]:
            PkgLine.create({"package_id": terr.id, "product_id": products[pk].id,
                            "quantity": qty, "required": req, "discount_percentage": disc})

        # --- Event orders ---
        SaleOrder = self.env["sale.order"]
        OrderLine = self.env["sale.order.line"]
        orders = {}
        order_specs = [
            ("boda", "aurora", "Boda García-López", "Hacienda San Ángel", 8,
             [("chair", 10), ("table", 2), ("speaker", 2), ("light", 4)]),
            ("gala", "granvia", "Gala Hotel Gran Vía", "Salón Imperial", 12,
             [("floor", 1), ("light", 4), ("speaker", 2)]),
        ]
        for okey, pk, ev, loc, day, lines in order_specs:
            order = SaleOrder.create({
                "partner_id": partners[pk].id,
                "x_is_event_rental": True,
                "x_event_name": ev, "x_event_location": loc,
                "x_event_start": self._at(day, 10), "x_event_end": self._at(day, 23),
                "x_billable_start": self._at(day, 10), "x_billable_end": self._at(day, 23),
                "x_block_start": self._at(day - 2, 8), "x_block_end": self._at(day + 2, 18),
                "x_logistics_notes": "Montaje T-2, desmontaje T+1, revisión T+2.",
            })
            for prod, qty in lines:
                OrderLine.create({
                    "order_id": order.id, "product_id": products[prod].id,
                    "product_uom_qty": qty,
                    "x_billable_start": self._at(day, 10), "x_billable_end": self._at(day, 23),
                    "x_block_start": self._at(day - 2, 8), "x_block_end": self._at(day + 2, 18),
                })
            orders[okey] = order

        # --- Reservations across all states (no overlap via availability) ---
        self._resv(products["chair"], 3, partners["aurora"], "released", -22, 8, -15, 18, policy="on_block_end")
        self._resv(products["table"], 1, partners["granvia"], "returned", -4, 8, -1, 18)
        self._resv(products["floor"], 1, partners["granvia"], "in_use", -1, 8, 3, 18, so=orders["gala"])
        self._resv(products["chair"], 10, partners["aurora"], "prepared", 6, 8, 10, 18, so=orders["boda"], bill=(8, 10, 23))
        self._resv(products["light"], 4, partners["aurora"], "reserved", 6, 8, 10, 18, so=orders["boda"])
        self._resv(products["speaker"], 2, partners["granvia"], "picked_up", 1, 8, 5, 18, so=orders["gala"])
        self._resv(products["light"], 3, partners["luna"], "soft_hold", 9, 8, 14, 18, policy="manual_only", soft_hours=2)
        self._resv(products["chair"], 2, partners["luna"], "quotation", 20, 8, 25, 18)
        self._resv(products["projector"], 1, partners["cumbre"], "draft", 22, 8, 27, 18)

        # --- Downtime ---
        Downtime = self.env["rental.serial.downtime"]
        Downtime.create({
            "lot_id": serials["speaker"][5].id, "reason": "maintenance",
            "state": "scheduled", "start_datetime": self._at(-2, 8),
            "end_datetime": self._at(3, 18), "notes": "Revisión de bocina post-evento"})
        Downtime.create({
            "lot_id": serials["chair"][19].id, "reason": "damaged",
            "state": "in_progress", "start_datetime": self._at(-5, 8),
            "notes": "Pata rota, fuera de servicio."})
        Downtime.create({
            "lot_id": serials["mic"][7].id, "reason": "lost",
            "state": "in_progress", "start_datetime": self._at(-10, 8),
            "notes": "Extraviado en evento, en investigación."})

        # --- Confirmed orders with real serial pickings (staggered dates) ---
        self._confirmed_order(products, partners, "Congreso Médico Anual", "zenith",
                              "Expo Center", -12, -15, -9,
                              [("mic", 2), ("screen", 1)], "closed")
        self._confirmed_order(products, partners, "Festival Gastronómico", "luna",
                              "Parque Central", 0, -2, 3,
                              [("heater", 2), ("table", 1)], "ongoing")
        self._confirmed_order(products, partners, "Lanzamiento de Producto", "cumbre",
                              "Showroom Cumbre", 18, 16, 20,
                              [("projector", 1), ("mic", 2)], "future")

    # ------------------------------------------------------------------
    def _resv(self, product, qty, partner, state, d1, h1, d2, h2,
              policy="on_return_validation", so=None, soft_hours=None, bill=None):
        svc = self.env["rental.availability.service"]
        Res = self.env["rental.serial.reservation"]
        start, end = self._at(d1, h1), self._at(d2, h2)
        available = svc.get_available_serials(product.id, start, end)
        for lot in available[:qty]:
            vals = {
                "partner_id": partner.id,
                "product_id": product.id,
                "lot_id": lot.id,
                "company_id": self.env.company.id,
                "state": state,
                "auto_release_policy": policy,
                "reservation_block_start": start,
                "reservation_block_end": end,
            }
            if so:
                vals["sale_order_id"] = so.id
            if bill:
                bd, bh1, bh2 = bill
                vals["rental_billable_start"] = self._at(bd, bh1)
                vals["rental_billable_end"] = self._at(bd, bh2)
            if soft_hours is not None:
                vals["soft_hold_until"] = datetime.now() + timedelta(hours=soft_hours)
                vals["soft_hold_owner_id"] = self.env.uid
                vals["soft_hold_reason"] = "Apartado mientras el cliente confirma"
            Res.create(vals)

    def _confirmed_order(self, products, partners, name, pk, loc, ev, bf, bt,
                         items, lifecycle):
        try:
            with self.env.cr.savepoint():
                wh = self.env["stock.warehouse"].search(
                    [("company_id", "=", self.env.company.id)], limit=1)
                stock_loc = wh.lot_stock_id
                svc = self.env["rental.availability.service"]
                Res = self.env["rental.serial.reservation"]
                order = self.env["sale.order"].create({
                    "partner_id": partners[pk].id,
                    "x_is_event_rental": True, "x_event_name": name,
                    "x_event_location": loc,
                    "x_event_start": self._at(ev, 10), "x_event_end": self._at(ev, 23),
                    "x_billable_start": self._at(ev, 10), "x_billable_end": self._at(ev, 23),
                    "x_block_start": self._at(bf, 8), "x_block_end": self._at(bt, 18),
                })
                reservations = Res
                for prod_key, qty in items:
                    product = products[prod_key]
                    line = self.env["sale.order.line"].create({
                        "order_id": order.id, "product_id": product.id,
                        "product_uom_qty": qty,
                        "x_billable_start": self._at(ev, 10), "x_billable_end": self._at(ev, 23),
                        "x_block_start": self._at(bf, 8), "x_block_end": self._at(bt, 18),
                    })
                    available = svc.get_available_serials(
                        product.id, self._at(bf, 8), self._at(bt, 18), stock_loc.id)
                    for lot in available[:qty]:
                        reservations |= Res.create({
                            "sale_order_id": order.id, "sale_order_line_id": line.id,
                            "partner_id": partners[pk].id, "product_id": product.id,
                            "lot_id": lot.id, "warehouse_id": wh.id,
                            "location_id": stock_loc.id, "company_id": self.env.company.id,
                            "rental_billable_start": self._at(ev, 10),
                            "rental_billable_end": self._at(ev, 23),
                            "reservation_block_start": self._at(bf, 8),
                            "reservation_block_end": self._at(bt, 18),
                            "state": "reserved",
                        })
                if lifecycle == "closed":
                    reservations.action_create_delivery_picking()
                    reservations.action_create_return_picking()
                    reservations.action_release()
                elif lifecycle == "ongoing":
                    reservations.action_create_delivery_picking()
                    reservations.write({"state": "in_use"})
                try:
                    with self.env.cr.savepoint():
                        order.write({"state": "sale"})
                except Exception:
                    pass
        except Exception:
            # A picking-path incompatibility must not abort the whole loader.
            pass
```

## ./wizard/rental_serial_assign_wizard_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_rental_serial_assign_wizard_form" model="ir.ui.view">
        <field name="name">rental.serial.assign.wizard.form</field>
        <field name="model">rental.serial.assign.wizard</field>
        <field name="arch" type="xml">
            <form string="Asignar series">
                <group>
                    <group>
                        <field name="product_id"/>
                        <field name="required_qty"/>
                    </group>
                    <group>
                        <field name="block_start"/>
                        <field name="block_end"/>
                        <field name="location_id"/>
                    </group>
                </group>
                <field name="line_ids">
                    <list editable="bottom" create="false" delete="false"
                          decoration-success="status == 'available'"
                          decoration-muted="status in ('no_stock','in_reservation')"
                          decoration-danger="status == 'blocked'">
                        <field name="status" widget="badge"
                               decoration-success="status == 'available'"
                               decoration-danger="status == 'blocked'"
                               decoration-info="status == 'in_reservation'"/>
                        <field name="lot_id"/>
                        <field name="selected"
                               readonly="status != 'available'"/>
                    </list>
                </field>
                <footer>
                    <button name="action_assign" type="object" string="Asignar seleccionadas"
                            class="btn-primary"/>
                    <button string="Cancelar" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>
</odoo>
```

## ./wizard/rental_serial_assign_wizard.py
```py
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
```

