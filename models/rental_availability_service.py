# -*- coding: utf-8 -*-
"""Centralised availability engine.

This is an ``AbstractModel`` so it can be called from anywhere with
``self.env['rental.availability.service']`` without creating database rows.
It is the single source of truth for *what is available* in a given
operational block period, computed per serial (``stock.lot``) rather than
per generic quantity.
"""
from odoo import api, models, fields

# States in which a reservation actually blocks a serial.
BLOCKING_STATES = (
    "soft_hold",
    "reserved",
    "prepared",
    "picked_up",
    "delivered",
    "in_use",
    "returned",  # physically not back-and-released yet -> still blocks
)

# Downtime states that block a serial.
DOWNTIME_BLOCKING_STATES = ("scheduled", "in_progress")


class RentalAvailabilityService(models.AbstractModel):
    _name = "rental.availability.service"
    _description = "Rental Serial Availability Engine"

    # ------------------------------------------------------------------
    # Low level helpers
    # ------------------------------------------------------------------
    @api.model
    def _normalise_period(self, block_start, block_end):
        if not block_start or not block_end:
            raise ValueError("An availability query requires a start and an end datetime.")
        if block_end <= block_start:
            raise ValueError("Operational block end must be after the start.")
        return block_start, block_end

    @api.model
    def _candidate_lots(self, product_id, location_id=None, company_id=None):
        """All serials that physically *could* be rented for a product.

        Filters: belongs to the product, not archived, currently in positive
        stock in an internal location. Maintenance/damage exclusion is handled
        through downtime records, not here, so historical lots stay queryable.
        """
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            return self.env["stock.lot"]

        domain = [("product_id", "=", product_id)]
        if company_id:
            domain.append(("company_id", "in", (company_id, False)))
        lots = self.env["stock.lot"].search(domain)

        # Keep only lots that have positive quantity in an internal location
        # (optionally restricted to a given location subtree).
        quant_domain = [
            ("lot_id", "in", lots.ids),
            ("quantity", ">", 0),
            ("location_id.usage", "=", "internal"),
        ]
        if location_id:
            location = self.env["stock.location"].browse(location_id)
            quant_domain.append(("location_id", "child_of", location.id))
        quants = self.env["stock.quant"].read_group(
            quant_domain, ["lot_id"], ["lot_id"]
        )
        lot_ids_with_stock = {g["lot_id"][0] for g in quants if g.get("lot_id")}
        return lots.filtered(lambda l: l.id in lot_ids_with_stock)

    @api.model
    def _reserved_lot_ids(self, lot_ids, block_start, block_end, ignore_reservation_ids=None):
        """Lot ids blocked by an overlapping reservation in the period."""
        if not lot_ids:
            return set()
        domain = [
            ("lot_id", "in", list(lot_ids)),
            ("state", "in", list(BLOCKING_STATES)),
            ("reservation_block_start", "<", block_end),
            ("reservation_block_end", ">", block_start),
        ]
        if ignore_reservation_ids:
            domain.append(("id", "not in", list(ignore_reservation_ids)))
        groups = self.env["rental.serial.reservation"].read_group(
            domain, ["lot_id"], ["lot_id"]
        )
        return {g["lot_id"][0] for g in groups if g.get("lot_id")}

    @api.model
    def _downtime_lot_ids(self, lot_ids, block_start, block_end):
        """Lot ids blocked by maintenance/damage/etc. in the period."""
        if not lot_ids:
            return set()
        domain = [
            ("lot_id", "in", list(lot_ids)),
            ("state", "in", list(DOWNTIME_BLOCKING_STATES)),
            ("start_datetime", "<", block_end),
            "|",
            ("end_datetime", "=", False),  # open-ended downtime blocks forever
            ("end_datetime", ">", block_start),
        ]
        groups = self.env["rental.serial.downtime"].read_group(
            domain, ["lot_id"], ["lot_id"]
        )
        return {g["lot_id"][0] for g in groups if g.get("lot_id")}

    # ------------------------------------------------------------------
    # Public API - serials
    # ------------------------------------------------------------------
    @api.model
    def get_available_serials(self, product_id, block_start, block_end,
                              location_id=None, ignore_reservation_ids=None):
        """Recordset of ``stock.lot`` free for the whole operational period."""
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(
            candidates.ids, block_start, block_end, ignore_reservation_ids)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        blocked = reserved | down
        return candidates.filtered(lambda l: l.id not in blocked)

    @api.model
    def get_unavailable_serials(self, product_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(candidates.ids, block_start, block_end)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        blocked = reserved | down
        return candidates.filtered(lambda l: l.id in blocked)

    # ------------------------------------------------------------------
    # Public API - product summary
    # ------------------------------------------------------------------
    @api.model
    def get_product_availability(self, product_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        company_id = self.env.company.id
        candidates = self._candidate_lots(product_id, location_id, company_id)
        reserved = self._reserved_lot_ids(candidates.ids, block_start, block_end)
        down = self._downtime_lot_ids(candidates.ids, block_start, block_end)
        available = candidates.filtered(lambda l: l.id not in (reserved | down))
        return {
            "product_id": product_id,
            "total_serials": len(candidates),
            "available_serials": available.ids,
            "reserved_serials": list(reserved),
            "unavailable_serials": list(down),
            "available_count": len(available),
            "reserved_count": len(reserved),
            "unavailable_count": len(down),
        }

    # ------------------------------------------------------------------
    # Public API - packages
    # ------------------------------------------------------------------
    @api.model
    def get_package_availability(self, package_id, block_start, block_end, location_id=None):
        block_start, block_end = self._normalise_period(block_start, block_end)
        package = self.env["rental.package.template"].browse(package_id)
        if not package.exists():
            return {"package_id": package_id, "max_packages": 0, "lines": []}

        line_results = []
        limits = []
        for line in package.line_ids.filtered(lambda l: l.required):
            product = line.product_id
            if product.tracking == "serial":
                avail = self.get_product_availability(
                    product.id, block_start, block_end, location_id)
                available_qty = avail["available_count"]
            else:
                # Non serial component: fall back to forecasted qty.
                available_qty = product.with_context(
                    to_date=block_start).free_qty
            possible = int(available_qty // line.quantity) if line.quantity else 0
            limits.append(possible)
            line_results.append({
                "line_id": line.id,
                "product_id": product.id,
                "product_name": product.display_name,
                "required_qty": line.quantity,
                "available_qty": available_qty,
                "possible_packages": possible,
                "is_limiting": False,
            })

        max_packages = min(limits) if limits else 0
        for res in line_results:
            res["is_limiting"] = res["possible_packages"] == max_packages
        return {
            "package_id": package_id,
            "package_name": package.display_name,
            "max_packages": max_packages,
            "lines": line_results,
        }
