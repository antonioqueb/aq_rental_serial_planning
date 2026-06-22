# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

SEVERITY_FACTOR = {"minor": 0.25, "major": 0.6, "total": 1.0}


class RentalDamageReport(models.Model):
    _name = "rental.damage.report"
    _description = "Acta de daño / faltante"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda s: _("Nuevo"))
    state = fields.Selection(
        [("draft", "Borrador"), ("confirmed", "Confirmada"),
         ("charged", "Cargada"), ("cancelled", "Cancelada")],
        default="draft", required=True, tracking=True, index=True)
    sale_order_id = fields.Many2one("sale.order", string="Pedido", index=True, ondelete="cascade")
    reservation_id = fields.Many2one("rental.serial.reservation", string="Reserva por serie")
    product_id = fields.Many2one("product.product", string="Producto", required=True)
    lot_id = fields.Many2one("stock.lot", string="Serie")
    quantity = fields.Float(string="Cantidad", default=1.0)
    damage_type = fields.Selection(
        [("damage", "Daño"), ("missing", "Faltante"), ("lost", "Perdido"), ("dirty", "Sucio")],
        string="Tipo", default="damage", required=True, tracking=True)
    severity = fields.Selection(
        [("minor", "Menor"), ("major", "Mayor"), ("total", "Total")],
        string="Severidad", default="minor", required=True)
    description = fields.Text(string="Descripción")
    replacement_value = fields.Monetary(string="Valor de reposición", currency_field="currency_id")
    suggested_charge = fields.Monetary(
        string="Cargo sugerido", compute="_compute_suggested_charge",
        store=True, readonly=False, currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id)
    charge_line_id = fields.Many2one("sale.order.line", string="Línea de cargo", readonly=True)
    block_serial = fields.Boolean(string="Bloquear serie", default=True)
    downtime_id = fields.Many2one("rental.serial.downtime", string="Bloqueo creado", readonly=True)
    evidence_attachment_ids = fields.Many2many("ir.attachment", string="Fotografías")
    customer_signature = fields.Binary(string="Firma del cliente")
    warehouse_signed_by = fields.Many2one("res.users", string="Reportado por", default=lambda s: s.env.user)
    partner_id = fields.Many2one("res.partner", related="sale_order_id.partner_id", store=True)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "rental.damage.report") or _("Nuevo")
        return super().create(vals_list)

    @api.depends("severity", "replacement_value", "quantity", "damage_type")
    def _compute_suggested_charge(self):
        for rec in self:
            if rec.damage_type in ("missing", "lost"):
                factor = 1.0
            else:
                factor = SEVERITY_FACTOR.get(rec.severity, 0.25)
            rec.suggested_charge = (rec.replacement_value or 0.0) * factor * (rec.quantity or 1.0)

    @api.onchange("reservation_id")
    def _onchange_reservation(self):
        if self.reservation_id:
            self.product_id = self.reservation_id.product_id
            self.lot_id = self.reservation_id.lot_id
            self.sale_order_id = self.reservation_id.sale_order_id
            self.replacement_value = self.reservation_id.product_id.lst_price

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_create_charge(self):
        Line = self.env["sale.order.line"]
        for rec in self:
            if not rec.sale_order_id:
                continue
            if rec.suggested_charge and not rec.charge_line_id:
                label = "%s: %s" % (
                    dict(self._fields["damage_type"].selection)[rec.damage_type],
                    rec.lot_id.name or rec.product_id.display_name)
                rec.charge_line_id = Line.create({
                    "order_id": rec.sale_order_id.id, "x_line_type": "manual_charge",
                    "name": _("Cargo por %s") % label,
                    "product_uom_qty": 1.0, "price_unit": rec.suggested_charge,
                })
            if rec.block_serial and rec.lot_id and not rec.downtime_id:
                rec.downtime_id = self.env["rental.serial.downtime"].create({
                    "lot_id": rec.lot_id.id,
                    "reason": "repair" if rec.damage_type == "damage" else (
                        "lost" if rec.damage_type in ("lost", "missing") else "cleaning"),
                    "state": "in_progress",
                    "start_datetime": fields.Datetime.now(),
                    "notes": _("Acta %s") % rec.name,
                })
            rec.state = "charged"
            rec.message_post(body=_("Cargo generado: %s") % (rec.suggested_charge))
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})
