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
