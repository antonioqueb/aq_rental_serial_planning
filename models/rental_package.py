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


LINE_TYPES = [
    ("serial_rental", "Renta por serie"),
    ("quantity_rental", "Renta por cantidad"),
    ("consumable_sale", "Venta / consumible"),
    ("service", "Servicio"),
    ("manual_charge", "Cargo manual"),
    ("manual_discount", "Descuento manual"),
    ("note", "Nota / línea informativa"),
]
# Line types that need an actual inventoried product.
_PRODUCT_REQUIRED_TYPES = ("serial_rental", "quantity_rental", "consumable_sale")


class RentalPackageTemplateLine(models.Model):
    _name = "rental.package.template.line"
    _description = "Componente de paquete de renta"
    _order = "sequence, id"

    package_id = fields.Many2one(
        "rental.package.template", string="Paquete", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Secuencia", default=10)
    line_type = fields.Selection(
        LINE_TYPES, string="Tipo de línea", required=True, default="quantity_rental")
    product_id = fields.Many2one(
        "product.product", string="Producto")
    name = fields.Char(string="Descripción")
    quantity = fields.Float(string="Cantidad", default=1.0)
    uom_id = fields.Many2one("uom.uom", string="UdM", related="product_id.uom_id", readonly=False)
    required = fields.Boolean(string="Requerido", default=True)
    optional = fields.Boolean(
        string="Opcional",
        compute="_compute_optional", inverse="_inverse_optional", store=True)
    allow_substitution = fields.Boolean(string="Permitir sustitución")
    allowed_substitute_product_ids = fields.Many2many(
        "product.product", "rental_pkg_line_substitute_rel",
        "line_id", "product_id", string="Sustitutos")
    discount_percentage = fields.Float(string="Descuento %")
    fixed_price = fields.Monetary(string="Precio fijo", currency_field="currency_id")
    currency_id = fields.Many2one(related="package_id.currency_id")
    tracking = fields.Selection(related="product_id.tracking", string="Seguimiento")
    # behaviour flags
    affects_availability = fields.Boolean(
        string="Afecta disponibilidad", compute="_compute_behaviour", store=True, readonly=False)
    show_on_quote = fields.Boolean(string="En cotización", default=True)
    show_on_invoice = fields.Boolean(string="En factura", default=True)
    show_on_picking_list = fields.Boolean(
        string="En checklist", compute="_compute_behaviour", store=True, readonly=False)
    requires_manager_approval = fields.Boolean(string="Requiere autorización")
    notes = fields.Char(string="Notas")

    @api.depends("line_type")
    def _compute_behaviour(self):
        for line in self:
            line.affects_availability = line.line_type in ("serial_rental", "quantity_rental")
            line.show_on_picking_list = line.line_type in (
                "serial_rental", "quantity_rental", "consumable_sale", "service")

    @api.onchange("product_id")
    def _onchange_product_line_type(self):
        """Classify the line from the product when first picked."""
        if self.product_id and not self._origin.line_type:
            if self.product_id.tracking == "serial":
                self.line_type = "serial_rental"
            elif self.product_id.type == "service":
                self.line_type = "service"
            else:
                self.line_type = "quantity_rental"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("line_type") and vals.get("product_id"):
                prod = self.env["product.product"].browse(vals["product_id"])
                vals["line_type"] = (
                    "serial_rental" if prod.tracking == "serial"
                    else "service" if prod.type == "service" else "quantity_rental")
        return super().create(vals_list)

    @api.depends("required")
    def _compute_optional(self):
        for line in self:
            line.optional = not line.required

    def _inverse_optional(self):
        for line in self:
            line.required = not line.optional

    @api.constrains("quantity", "line_type")
    def _check_quantity(self):
        for line in self:
            if line.line_type not in ("manual_charge", "manual_discount", "note") and line.quantity <= 0:
                raise ValidationError(_("La cantidad del componente debe ser positiva."))

    @api.constrains("line_type", "product_id", "tracking")
    def _check_line_product(self):
        for line in self:
            if line.line_type in _PRODUCT_REQUIRED_TYPES and not line.product_id:
                raise ValidationError(_(
                    "El tipo de línea '%s' requiere un producto.",
                    dict(LINE_TYPES)[line.line_type]))
            if line.line_type == "serial_rental" and line.product_id and line.product_id.tracking != "serial":
                raise ValidationError(_(
                    "La línea de renta por serie requiere un producto con seguimiento por número de serie."))

    @api.model
    def _migrate_classify_line_types(self):
        """Set line_type on legacy lines (run once from a data <function>)."""
        for line in self.search([]):
            if line.line_type:
                continue
            if line.product_id.tracking == "serial":
                line.line_type = "serial_rental"
            elif line.product_id.type == "service":
                line.line_type = "service"
            else:
                line.line_type = "quantity_rental"
