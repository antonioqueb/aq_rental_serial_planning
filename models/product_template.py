# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_rental_serial_planning = fields.Boolean(
        string="Serial Rental Planning",
        help="Enable serial-level reservation planning for this rentable product.",
    )
    x_requires_serial_reservation = fields.Boolean(
        string="Requires Serial Reservation",
        help="Specific serials must be assigned before the reservation can be "
             "confirmed. Implies tracking by serial number.",
    )
    x_allow_auto_serial_assignment = fields.Boolean(
        string="Allow Auto Assignment", default=True)
    x_allow_manual_serial_assignment = fields.Boolean(
        string="Allow Manual Assignment", default=True)
    x_rental_package_eligible = fields.Boolean(
        string="Package Eligible", default=True,
        help="May be used as a component inside a rental package.")

    # Default operational buffers (hours) used to derive the block period
    # from the billable period.
    x_default_preparation_hours = fields.Float(string="Preparation (h)", default=0.0)
    x_default_delivery_buffer_hours = fields.Float(string="Delivery Buffer (h)", default=0.0)
    x_default_return_buffer_hours = fields.Float(string="Return Buffer (h)", default=0.0)
    x_default_cleaning_hours = fields.Float(string="Cleaning/Review (h)", default=0.0)

    @api.constrains("x_requires_serial_reservation", "tracking")
    def _check_serial_tracking(self):
        for tmpl in self:
            if tmpl.x_requires_serial_reservation and tmpl.tracking != "serial":
                raise ValidationError(_(
                    "Product '%s' requires serial reservation, so its tracking "
                    "must be set to 'By Unique Serial Number'.", tmpl.display_name))

    @api.onchange("x_requires_serial_reservation")
    def _onchange_requires_serial(self):
        if self.x_requires_serial_reservation:
            self.x_rental_serial_planning = True
            self.rent_ok = True
            if self.tracking != "serial":
                self.tracking = "serial"
