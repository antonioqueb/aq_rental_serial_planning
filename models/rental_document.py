# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

DOC_TYPES = [
    ("quote", "Cotización"),
    ("rental_contract", "Contrato de renta"),
    ("liability_letter", "Carta responsiva"),
    ("outgoing_checklist", "Checklist de salida"),
    ("return_checklist", "Checklist de retorno"),
    ("mounting_sheet", "Hoja de montaje"),
    ("damage_report", "Acta de daño / faltante"),
    ("custom", "Personalizado"),
]


class RentalDocumentTemplate(models.Model):
    _name = "rental.document.template"
    _description = "Plantilla de documento de renta"
    _order = "document_type, name"

    name = fields.Char(required=True)
    document_type = fields.Selection(DOC_TYPES, string="Tipo", required=True, default="custom")
    active = fields.Boolean(default=True)
    body_html = fields.Html(string="Cuerpo / términos", sanitize=False)
    requires_customer_signature = fields.Boolean(string="Firma del cliente")
    requires_warehouse_signature = fields.Boolean(string="Firma de almacén")
    requires_internal_approval = fields.Boolean(string="Aprobación interna")
    show_serial_lines = fields.Boolean(string="Mostrar series", default=True)
    show_quantity_lines = fields.Boolean(string="Mostrar cantidades", default=True)
    show_consumables = fields.Boolean(string="Mostrar consumibles", default=True)
    show_services = fields.Boolean(string="Mostrar servicios", default=True)
    show_prices = fields.Boolean(string="Mostrar precios", default=True)
    show_terms = fields.Boolean(string="Mostrar términos")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)


class RentalDocumentInstance(models.Model):
    _name = "rental.document.instance"
    _description = "Documento de renta generado"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda s: _("Nuevo"))
    document_type = fields.Selection(DOC_TYPES, string="Tipo", required=True, default="custom")
    sale_order_id = fields.Many2one("sale.order", string="Pedido", index=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", string="Cliente")
    template_id = fields.Many2one("rental.document.template", string="Plantilla")
    state = fields.Selection(
        [("draft", "Borrador"), ("generated", "Generado"), ("sent", "Enviado"),
         ("signed", "Firmado"), ("cancelled", "Cancelado")],
        default="draft", required=True, tracking=True, index=True)
    pdf_attachment_id = fields.Many2one("ir.attachment", string="PDF", readonly=True)
    evidence_attachment_ids = fields.Many2many("ir.attachment", string="Evidencia fotográfica")
    # signatures (fallback when Odoo Sign is not used)
    customer_signature = fields.Binary(string="Firma del cliente")
    customer_signed_by = fields.Char(string="Firmado por (cliente)")
    customer_signed_date = fields.Datetime(string="Fecha firma cliente")
    warehouse_signature = fields.Binary(string="Firma de almacén")
    warehouse_signed_by = fields.Many2one("res.users", string="Firmado por (almacén)")
    warehouse_signed_date = fields.Datetime(string="Fecha firma almacén")
    notes = fields.Text(string="Notas")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.document.instance") or _("Nuevo")
            if not vals.get("template_id") and vals.get("document_type"):
                tmpl = self.env["rental.document.template"].search(
                    [("document_type", "=", vals["document_type"])], limit=1)
                vals["template_id"] = tmpl.id or False
        return super().create(vals_list)

    def action_print(self):
        self.ensure_one()
        if self.state == "draft":
            self.state = "generated"
        return self.env.ref(
            "aq_rental_serial_planning.action_report_rental_document").report_action(self)

    def action_send(self):
        for d in self:
            d.state = "sent"
            d.message_post(body=_("Documento enviado al cliente."))

    def action_mark_signed(self):
        for d in self:
            if d.customer_signature and not d.customer_signed_date:
                d.customer_signed_date = fields.Datetime.now()
            if d.warehouse_signature and not d.warehouse_signed_date:
                d.warehouse_signed_date = fields.Datetime.now()
                d.warehouse_signed_by = self.env.user
            d.state = "signed"
            d.message_post(body=_("Documento firmado."))

    def action_cancel(self):
        self.write({"state": "cancelled"})
