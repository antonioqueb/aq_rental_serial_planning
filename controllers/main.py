# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request

from ..models.rental_availability_service import BLOCKING_STATES


def _parse_dt(value):
    if not value:
        return None
    return fields.Datetime.to_datetime(value)


class RentalPlanningController(http.Controller):
    """JSON endpoints feeding the OWL timeline board.

    All endpoints are ``auth='user'`` and rely on Odoo's record rules /
    multi-company isolation, so no extra company filtering is needed beyond
    the active company set on the request.
    """

    # ------------------------------------------------------------------
    # Board data: products -> serials -> reservation/downtime blocks
    # ------------------------------------------------------------------
    @http.route("/rental_serial_planning/serial_timeline", type="json", auth="user")
    def serial_timeline(self, date_start, date_end, product_ids=None,
                        warehouse_id=None, location_id=None, partner_id=None,
                        states=None, package_id=None, **kw):
        env = request.env
        start = _parse_dt(date_start)
        end = _parse_dt(date_end)

        product_domain = [("tracking", "=", "serial"),
                          ("x_rental_serial_planning", "=", True)]
        if product_ids:
            product_domain = [("id", "in", product_ids)]
        if package_id:
            pkg = env["rental.package.template"].browse(int(package_id))
            product_domain = [("id", "in", pkg.line_ids.mapped("product_id").ids)]
        products = env["product.product"].search(product_domain)

        lot_domain = [("product_id", "in", products.ids)]
        lots = env["stock.lot"].search(lot_domain)

        res_domain = [
            ("lot_id", "in", lots.ids),
            ("reservation_block_start", "<", end),
            ("reservation_block_end", ">", start),
            ("state", "not in", ("cancelled",)),
        ]
        if partner_id:
            res_domain.append(("partner_id", "=", int(partner_id)))
        if warehouse_id:
            res_domain.append(("warehouse_id", "=", int(warehouse_id)))
        if states:
            res_domain.append(("state", "in", states))
        reservations = env["rental.serial.reservation"].search(res_domain)

        dt_domain = [
            ("lot_id", "in", lots.ids),
            ("state", "in", ("scheduled", "in_progress")),
            ("start_datetime", "<", end),
            "|", ("end_datetime", "=", False), ("end_datetime", ">", start),
        ]
        downtimes = env["rental.serial.downtime"].search(dt_domain)

        # Build nested structure: product -> serials -> blocks
        res_by_lot = {}
        for r in reservations:
            res_by_lot.setdefault(r.lot_id.id, []).append({
                "id": r.id, "type": "reservation", "name": r.name,
                "state": r.state, "partner": r.partner_id.display_name,
                "sale_order_id": r.sale_order_id.id,
                "sale_order": r.sale_order_id.name,
                "billable_start": r.rental_billable_start and r.rental_billable_start.isoformat(),
                "billable_end": r.rental_billable_end and r.rental_billable_end.isoformat(),
                "start": r.reservation_block_start.isoformat(),
                "end": r.reservation_block_end.isoformat(),
                "conflict": r.conflict_status == "conflict",
            })
        dt_by_lot = {}
        for d in downtimes:
            dt_by_lot.setdefault(d.lot_id.id, []).append({
                "id": d.id, "type": "downtime", "name": d.name,
                "state": "maintenance", "reason": d.reason,
                "start": d.start_datetime.isoformat(),
                "end": (d.end_datetime or end).isoformat(),
                "conflict": False,
            })

        result = []
        for product in products:
            product_lots = lots.filtered(lambda l: l.product_id == product)
            serial_rows = []
            for lot in product_lots:
                blocks = res_by_lot.get(lot.id, []) + dt_by_lot.get(lot.id, [])
                serial_rows.append({
                    "lot_id": lot.id,
                    "lot_name": lot.name,
                    "blocks": blocks,
                })
            result.append({
                "product_id": product.id,
                "product_name": product.display_name,
                "serial_count": len(product_lots),
                "serials": serial_rows,
            })
        return {
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "products": result,
            "blocking_states": list(BLOCKING_STATES),
        }

    # ------------------------------------------------------------------
    # Availability lookups
    # ------------------------------------------------------------------
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
        service = request.env["rental.availability.service"]
        lots = service.get_available_serials(
            int(product_id), _parse_dt(block_start), _parse_dt(block_end),
            int(location_id) if location_id else None)
        return [{"id": l.id, "name": l.name} for l in lots]

    # ------------------------------------------------------------------
    # Filter metadata for the board toolbar
    # ------------------------------------------------------------------
    @http.route("/rental_serial_planning/filters", type="json", auth="user")
    def filters(self, **kw):
        env = request.env
        return {
            "warehouses": [{"id": w.id, "name": w.name}
                           for w in env["stock.warehouse"].search([])],
            "products": [{"id": p.id, "name": p.display_name}
                         for p in env["product.product"].search(
                             [("tracking", "=", "serial"),
                              ("x_rental_serial_planning", "=", True)])],
            "packages": [{"id": p.id, "name": p.display_name}
                         for p in env["rental.package.template"].search([])],
            "states": [{"key": k, "label": v} for k, v in
                       env["rental.serial.reservation"]._fields["state"].selection],
        }

    # ------------------------------------------------------------------
    # Quick actions from the board
    # ------------------------------------------------------------------
    @http.route("/rental_serial_planning/release", type="json", auth="user")
    def release(self, reservation_ids, **kw):
        recs = request.env["rental.serial.reservation"].browse(reservation_ids)
        recs.action_release()
        return {"released": recs.ids}

    @http.route("/rental_serial_planning/create_downtime", type="json", auth="user")
    def create_downtime(self, lot_id, reason, start, end=None, **kw):
        dt = request.env["rental.serial.downtime"].create({
            "lot_id": int(lot_id),
            "reason": reason,
            "start_datetime": _parse_dt(start),
            "end_datetime": _parse_dt(end) if end else False,
        })
        return {"downtime_id": dt.id}
