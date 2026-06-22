# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

RESOLUTIONS = [
    ("purchase", "Compra / requisición"),
    ("subrent", "Subrenta"),
    ("subcontract", "Subcontratación"),
    ("manual_task", "Tarea manual"),
    ("ignore", "Solo advertir"),
]


class RentalShortagePolicy(models.Model):
    _name = "rental.shortage.policy"
    _description = "Política de shortage / sobreventa"
    _order = "priority, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    priority = fields.Integer(default=10)
    scope = fields.Selection(
        [("global", "Global"), ("product", "Producto"),
         ("category", "Categoría"), ("package", "Paquete")],
        string="Alcance", default="global", required=True)
    product_id = fields.Many2one("product.product", string="Producto")
    category_id = fields.Many2one("product.category", string="Categoría")
    package_id = fields.Many2one("rental.package.template", string="Paquete")

    allow_shortage = fields.Boolean(string="Permitir shortage", default=True)
    shortage_type = fields.Selection(
        [("quantity", "Cantidad"), ("percent", "Porcentaje")],
        string="Tipo de límite", default="quantity", required=True)
    max_shortage_qty = fields.Float(string="Faltante máx. (uds)")
    max_shortage_percent = fields.Float(string="Faltante máx. (%)")
    requires_manager_approval = fields.Boolean(string="Requiere autorización")
    default_resolution = fields.Selection(
        RESOLUTIONS, string="Resolución por defecto", default="manual_task", required=True)
    vendor_id = fields.Many2one("res.partner", string="Proveedor")
    subrent_product_id = fields.Many2one("product.product", string="Producto de subrenta")
    lead_time_days = fields.Integer(string="Lead time (días)", default=2)
    internal_notes = fields.Text(string="Notas internas")
    customer_visible_label = fields.Char(string="Etiqueta para el cliente", default="Por confirmar")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)

    @api.model
    def _find_policy(self, product, package=None):
        """Most specific active policy: package/product > category > global."""
        policies = self.search([
            ("active", "=", True),
            ("company_id", "in", (self.env.company.id, False))])
        cat_ids = []
        if product and product.categ_id and product.categ_id.parent_path:
            cat_ids = [int(x) for x in product.categ_id.parent_path.split("/") if x]
        best, best_key = self.browse(), (-1, 0)
        for p in policies:
            if p.scope == "global":
                spec = 0
            elif p.scope == "product" and product and p.product_id == product:
                spec = 3
            elif p.scope == "package" and package and p.package_id == package:
                spec = 2
            elif p.scope == "category" and p.category_id and p.category_id.id in cat_ids:
                spec = 1
            else:
                continue
            key = (spec, -p.priority)
            if key > best_key:
                best, best_key = p, key
        return best

    def evaluate(self, requested, available):
        """Return how a shortage should be handled. Safe on an empty recordset."""
        shortage = max(0.0, requested - available)
        if shortage <= 0:
            return {"status": "available", "shortage_qty": 0.0,
                    "allowed": True, "requires_approval": False}
        if not self or not self.allow_shortage:
            return {"status": "not_available", "shortage_qty": shortage,
                    "allowed": False, "requires_approval": False}
        if self.shortage_type == "percent":
            limit = requested * (self.max_shortage_percent or 0.0) / 100.0
        else:
            limit = self.max_shortage_qty or 0.0
        if shortage > limit:
            return {"status": "not_available", "shortage_qty": shortage,
                    "allowed": False, "requires_approval": False}
        if self.requires_manager_approval:
            return {"status": "requires_manager_approval", "shortage_qty": shortage,
                    "allowed": True, "requires_approval": True}
        return {"status": "available_with_shortage", "shortage_qty": shortage,
                "allowed": True, "requires_approval": False}


class RentalShortageNeed(models.Model):
    _name = "rental.shortage.need"
    _description = "Faltante por conseguir"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "deadline, id"

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda s: _("Nuevo"))
    state = fields.Selection(
        [("draft", "Borrador"), ("pending", "Pendiente de autorización"),
         ("approved", "Autorizado"), ("in_procurement", "En gestión"),
         ("sourced", "Conseguido"), ("cancelled", "Cancelado")],
        default="draft", required=True, tracking=True, index=True)
    sale_order_id = fields.Many2one("sale.order", string="Pedido", index=True, ondelete="cascade")
    sale_order_line_id = fields.Many2one("sale.order.line", string="Línea", ondelete="cascade")
    quantity_reservation_id = fields.Many2one("rental.quantity.reservation", string="Reserva por cantidad")
    product_id = fields.Many2one("product.product", string="Producto", required=True, index=True)
    package_id = fields.Many2one("rental.package.template", string="Paquete")
    partner_id = fields.Many2one("res.partner", string="Cliente")
    event_date = fields.Date(string="Fecha del evento")
    reservation_block_start = fields.Datetime(string="Inicio de bloqueo")
    reservation_block_end = fields.Datetime(string="Fin de bloqueo")
    requested_qty = fields.Float(string="Solicitado")
    available_qty = fields.Float(string="Disponible")
    shortage_qty = fields.Float(string="Faltante", required=True)
    policy_id = fields.Many2one("rental.shortage.policy", string="Política")
    resolution_type = fields.Selection(RESOLUTIONS, string="Resolución")
    vendor_id = fields.Many2one("res.partner", string="Proveedor")
    responsible_id = fields.Many2one("res.users", string="Responsable", default=lambda s: s.env.user)
    deadline = fields.Date(string="Fecha límite")
    notes = fields.Text(string="Notas")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.shortage.need") or _("Nuevo")
        return super().create(vals_list)

    def _auto_resolve(self):
        for need in self:
            rt = need.resolution_type or (
                need.policy_id.default_resolution if need.policy_id else "manual_task")
            need.resolution_type = rt
            if rt == "ignore":
                need.state = "draft"
                continue
            if need.state in ("draft", "pending", "approved"):
                need.state = "in_procurement"
            user = need.responsible_id or self.env.user
            try:
                need.activity_schedule(
                    "mail.mail_activity_data_todo", user_id=user.id,
                    summary=_("Conseguir faltante: %s") % need.product_id.display_name,
                    note=_("Faltan %(q)s unidades de %(p)s. Resolución: %(r)s.") % {
                        "q": int(need.shortage_qty), "p": need.product_id.display_name,
                        "r": dict(RESOLUTIONS).get(rt, rt)})
            except Exception:  # pragma: no cover - activity type may be missing
                pass

    def action_approve(self):
        self.write({"state": "approved"})

    def action_start_procurement(self):
        self._auto_resolve()

    def action_sourced(self):
        self.write({"state": "sourced"})

    def action_cancel(self):
        self.write({"state": "cancelled"})
