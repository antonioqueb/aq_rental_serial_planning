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
