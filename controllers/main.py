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
