# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.rental_serial_substitution import SUBSTITUTION_REASONS


class RentalSerialSubstitutionWizard(models.TransientModel):
    _name = "rental.serial.substitution.wizard"
    _description = "Sustituir serie comprometida"

    reservation_id = fields.Many2one(
        "rental.serial.reservation", string="Reserva", required=True)
    product_id = fields.Many2one("product.product", string="Producto", readonly=True)
    old_lot_id = fields.Many2one("stock.lot", string="Serie actual", readonly=True)
    block_start = fields.Datetime(string="Inicio de bloqueo", readonly=True)
    block_end = fields.Datetime(string="Fin de bloqueo", readonly=True)
    available_lot_ids = fields.Many2many("stock.lot", string="Series disponibles")
    new_lot_id = fields.Many2one(
        "stock.lot", string="Nueva serie", required=True,
        domain="[('id', 'in', available_lot_ids)]")
    reason = fields.Selection(
        SUBSTITUTION_REASONS, string="Motivo", required=True, default="damaged")
    notes = fields.Text(string="Notas")
    create_downtime_for_old_lot = fields.Boolean(
        string="Bloquear la serie anterior", default=True,
        help="Crea un bloqueo (mantenimiento/daño) abierto para la serie que se "
             "retira, para que no vuelva a reservarse hasta resolverla.")
    downtime_reason = fields.Selection(
        [("maintenance", "Mantenimiento"), ("repair", "Reparación"),
         ("damaged", "Dañado"), ("lost", "Perdido"),
         ("cleaning", "Limpieza"), ("other", "Otro")],
        string="Motivo del bloqueo", default="damaged")
    notify_users = fields.Boolean(string="Notificar a seguidores", default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        reservation = self.env["rental.serial.reservation"].browse(
            res.get("reservation_id") or self.env.context.get("active_id"))
        if reservation.exists():
            res.update({
                "reservation_id": reservation.id,
                "product_id": reservation.product_id.id,
                "old_lot_id": reservation.lot_id.id,
                "block_start": reservation.reservation_block_start,
                "block_end": reservation.reservation_block_end,
            })
            available = self.env["rental.availability.service"].get_available_serials(
                reservation.product_id.id,
                reservation.reservation_block_start,
                reservation.reservation_block_end,
                reservation.location_id.id or None,
                ignore_reservation_ids=reservation.ids)
            available = available - reservation.lot_id
            res["available_lot_ids"] = [(6, 0, available.ids)]
        return res

    def action_substitute(self):
        self.ensure_one()
        reservation = self.reservation_id
        if not reservation.lot_id:
            raise UserError(_("La reserva no tiene una serie asignada."))
        if self.new_lot_id.product_id != reservation.product_id:
            raise UserError(_("La nueva serie no pertenece a este producto."))
        if self.new_lot_id not in self.available_lot_ids:
            raise UserError(_(
                "La serie '%s' ya no está disponible para este periodo operativo.",
                self.new_lot_id.name))

        old_lot = reservation.lot_id
        downtime = self.env["rental.serial.downtime"]
        if self.create_downtime_for_old_lot:
            downtime = self.env["rental.serial.downtime"].create({
                "lot_id": old_lot.id,
                "reason": self.downtime_reason,
                "state": "in_progress",
                "start_datetime": fields.Datetime.now(),
                "notes": _("Bloqueo automático por sustitución (%s).") % (
                    dict(SUBSTITUTION_REASONS).get(self.reason)),
            })

        # swap the serial on the reservation (validates conflicts via write)
        reservation.lot_id = self.new_lot_id

        self.env["rental.serial.substitution.log"].create({
            "reservation_id": reservation.id,
            "product_id": reservation.product_id.id,
            "old_lot_id": old_lot.id,
            "new_lot_id": self.new_lot_id.id,
            "reason": self.reason,
            "notes": self.notes,
            "old_downtime_id": downtime.id if downtime else False,
        })

        body = _(
            "Sustitución de serie: %(old)s → %(new)s (motivo: %(reason)s).",
            old=old_lot.name, new=self.new_lot_id.name,
            reason=dict(SUBSTITUTION_REASONS).get(self.reason))
        if self.notes:
            body += "<br/>%s" % self.notes
        reservation.message_post(body=body)
        if self.notify_users and reservation.sale_order_id:
            reservation.sale_order_id.message_post(body=body)
        return {"type": "ir.actions.act_window_close"}
