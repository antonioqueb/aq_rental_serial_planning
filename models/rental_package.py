# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RentalPackageTemplate(models.Model):
    _name = "rental.package.template"
    _description = "Rental Package / Bundle Template"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string="Internal Reference", copy=False)
    active = fields.Boolean(default=True)
    description = fields.Text()
    sale_product_id = fields.Many2one(
        "product.product", string="Commercial Product",
        help="Optional parent product shown as a single line on the quotation. "
             "Should be a service/rentable product representing the package.")
    line_ids = fields.One2many(
        "rental.package.template.line", "package_id", string="Components",
        copy=True)
    pricing_policy = fields.Selection(
        [("sum_components", "Sum of components"),
         ("fixed_package_price", "Fixed package price"),
         ("discount_components", "Components with discount")],
        default="sum_components", required=True)
    fixed_price = fields.Monetary(string="Fixed Price")
    hide_components_on_quote = fields.Boolean(string="Hide Components on Quotation")
    hide_components_on_invoice = fields.Boolean(string="Hide Components on Invoice")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)

    component_count = fields.Integer(compute="_compute_component_count")

    @api.depends("line_ids")
    def _compute_component_count(self):
        for pkg in self:
            pkg.component_count = len(pkg.line_ids)

    @api.constrains("line_ids")
    def _check_has_lines(self):
        for pkg in self:
            if not pkg.line_ids:
                raise ValidationError(_("A package must contain at least one component."))

    def action_check_availability(self):
        """Open a transient summary of package availability (used by smart button)."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "aq_rental_planning_board",
            "name": _("Package availability: %s") % self.display_name,
            "params": {"package_id": self.id},
        }


class RentalPackageTemplateLine(models.Model):
    _name = "rental.package.template.line"
    _description = "Rental Package Component"
    _order = "sequence, id"

    package_id = fields.Many2one(
        "rental.package.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product", required=True,
        domain="[('x_rental_package_eligible', '=', True)]")
    quantity = fields.Float(string="Quantity", default=1.0, required=True)
    required = fields.Boolean(default=True)
    optional = fields.Boolean(
        compute="_compute_optional", inverse="_inverse_optional", store=True)
    allow_substitution = fields.Boolean(string="Allow Substitution")
    allowed_substitute_product_ids = fields.Many2many(
        "product.product", "rental_pkg_line_substitute_rel",
        "line_id", "product_id", string="Substitutes")
    discount_percentage = fields.Float(string="Discount %")
    tracking = fields.Selection(related="product_id.tracking", string="Tracking")
    notes = fields.Char()

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
                raise ValidationError(_("Component quantity must be positive."))
