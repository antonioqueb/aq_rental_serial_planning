# -*- coding: utf-8 -*-
"""On-demand sample data loader.

Odoo only loads ``demo/`` files when the database was created *with
demonstration data*. On production/QA databases created without it, this
wizard lets an administrator populate a full, realistic dataset on demand
(products + serials + stock, customers, packages, event orders, reservations
in every state, downtime, and confirmed orders with real serial pickings).

Idempotent: it refuses to run twice (marker product check).
"""
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# key, name, n_serials, default_code, price, (prep, deliv, ret, clean), requires_serial
_PRODUCTS = [
    ("chair", "Sillas Manhattan", 20, "AQ-SILLA", 45.0, (4, 12, 12, 6), True),
    ("table", "Mesa Banquete Redonda", 8, "AQ-MESA", 120.0, (4, 12, 12, 8), True),
    ("speaker", "Bocina JBL EON 715", 6, "AQ-BOC", 260.0, (2, 6, 6, 4), True),
    ("light", "Luz PAR LED RGB", 12, "AQ-PAR", 80.0, (2, 6, 6, 3), True),
    ("tent", "Carpa 6x6 Cristal", 3, "AQ-CARPA", 1500.0, (24, 24, 24, 24), True),
    ("projector", "Proyector Epson 5000L", 4, "AQ-PROY", 450.0, (3, 6, 6, 4), True),
    ("screen", "Pantalla Proyección 120in", 4, "AQ-PANT", 180.0, (3, 6, 6, 2), True),
    ("floor", "Pista de Baile Módulo", 10, "AQ-PISTA", 150.0, (8, 12, 12, 10), True),
    ("heater", "Calentador de Patio", 5, "AQ-CALEN", 140.0, (2, 6, 6, 4), True),
    ("mic", "Micrófono Inalámbrico Shure", 8, "AQ-MIC", 90.0, (1, 4, 4, 2), True),
]

_PARTNERS = [
    ("aurora", "Bodas Aurora", "contacto@bodasaurora.mx"),
    ("zenith", "Corporativo Zenith", "eventos@zenith.com"),
    ("luna", "Eventos Luna", "hola@eventosluna.mx"),
    ("granvia", "Hotel Gran Vía", "banquetes@granvia.mx"),
    ("cumbre", "Productora Cumbre", "produccion@cumbre.tv"),
]


class RentalSampleDataWizard(models.TransientModel):
    _name = "rental.sample.data.wizard"
    _description = "Cargar datos de ejemplo de renta"

    @api.model
    def _already_loaded(self):
        return bool(self.env["product.product"].search_count(
            [("default_code", "=", "AQ-SILLA")]))

    @api.model
    def _load_sample_data_auto(self):
        """Idempotently create the sample dataset.

        Called from a ``<function>`` data tag so it runs on EVERY install and
        update, regardless of the database demo flag. Must never raise: a
        failure here cannot be allowed to abort module loading.
        """
        if self._already_loaded():
            return
        try:
            with self.env.cr.savepoint():
                self._create_all()
            _logger.info("AQ Rental: datos de ejemplo creados automáticamente.")
        except Exception:
            _logger.exception(
                "AQ Rental: fallo al crear los datos de ejemplo automáticos.")

    def action_load(self):
        self.ensure_one()
        if self._already_loaded():
            raise UserError(_(
                "Los datos de ejemplo ya fueron cargados anteriormente."))
        self._create_all()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Datos de ejemplo cargados"),
                "message": _("Catálogo, clientes, paquetes, órdenes, reservas, "
                             "downtime y pedidos confirmados con transferencias "
                             "fueron creados. Abre el Tablero de Planeación."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    # ------------------------------------------------------------------
    @api.model
    def _at(self, day, hour):
        return (datetime.now() + timedelta(days=day)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

    def _create_all(self):
        company = self.env.company
        stock_loc = self.env.ref("stock.stock_location_stock")
        Product = self.env["product.product"]
        Lot = self.env["stock.lot"]
        Quant = self.env["stock.quant"]

        categ = self.env["product.category"].create({"name": "Renta de Eventos"})

        # --- Products + serials + stock ---
        products = {}
        serials = {}
        for key, name, n, code, price, buf, req in _PRODUCTS:
            pre, deliv, ret, clean = buf
            product = Product.create({
                "name": name,
                "default_code": code,
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
                "rent_ok": True,
                "list_price": price,
                "categ_id": categ.id,
                "x_rental_serial_planning": True,
                "x_requires_serial_reservation": req,
                "x_rental_package_eligible": True,
                "x_default_preparation_hours": pre,
                "x_default_delivery_buffer_hours": deliv,
                "x_default_return_buffer_hours": ret,
                "x_default_cleaning_hours": clean,
            })
            products[key] = product
            lots = Lot.create([
                {"name": "%s-%03d" % (code.replace("AQ-", ""), i),
                 "product_id": product.id, "company_id": company.id}
                for i in range(1, n + 1)])
            serials[key] = lots
            Quant.create([
                {"product_id": product.id, "lot_id": lot.id,
                 "location_id": stock_loc.id, "quantity": 1.0}
                for lot in lots])

        # Non-serial consumables (package substitution demo)
        linen = Product.create({
            "name": "Mantel Premium Blanco", "default_code": "AQ-MANTEL-B",
            "type": "consu", "is_storable": True, "rent_ok": True,
            "list_price": 25.0, "categ_id": categ.id,
            "x_rental_package_eligible": True})
        linen_alt = Product.create({
            "name": "Mantel Premium Negro", "default_code": "AQ-MANTEL-N",
            "type": "consu", "is_storable": True, "rent_ok": True,
            "list_price": 25.0, "categ_id": categ.id,
            "x_rental_package_eligible": True})

        # --- Partners ---
        partners = {}
        for key, name, email in _PARTNERS:
            partners[key] = self.env["res.partner"].create({
                "name": name, "email": email,
                "is_company": True, "customer_rank": 1})

        # --- Packages ---
        Pkg = self.env["rental.package.template"]
        PkgLine = self.env["rental.package.template.line"]
        boda = Pkg.create({
            "name": "Paquete Boda Premium", "code": "PKG-BODA",
            "pricing_policy": "sum_components",
            "description": "Mobiliario y audio para boda de hasta 100 invitados."})
        for pk, qty, req in [("chair", 10, True), ("table", 2, True),
                             ("speaker", 2, True), ("light", 4, True), ("floor", 1, False)]:
            PkgLine.create({"package_id": boda.id, "product_id": products[pk].id,
                            "quantity": qty, "required": req})
        PkgLine.create({
            "package_id": boda.id, "product_id": linen.id, "quantity": 12,
            "required": True, "allow_substitution": True,
            "allowed_substitute_product_ids": [(6, 0, [linen_alt.id])]})

        conf = Pkg.create({
            "name": "Paquete Conferencia Corporativa", "code": "PKG-CONF",
            "pricing_policy": "fixed_package_price", "fixed_price": 3500.0,
            "hide_components_on_quote": True,
            "description": "Proyección, audio y asientos para conferencia."})
        for pk, qty in [("projector", 1), ("screen", 1), ("speaker", 2),
                        ("mic", 2), ("chair", 15)]:
            PkgLine.create({"package_id": conf.id, "product_id": products[pk].id,
                            "quantity": qty, "required": True})

        terr = Pkg.create({
            "name": "Paquete Terraza Otoño", "code": "PKG-TERR",
            "pricing_policy": "discount_components",
            "description": "Carpa, calefacción y mesas para terraza."})
        for pk, qty, req, disc in [("tent", 1, True, 0), ("heater", 4, True, 10),
                                   ("table", 4, True, 5), ("light", 6, False, 0)]:
            PkgLine.create({"package_id": terr.id, "product_id": products[pk].id,
                            "quantity": qty, "required": req, "discount_percentage": disc})

        # --- Event orders ---
        SaleOrder = self.env["sale.order"]
        OrderLine = self.env["sale.order.line"]
        orders = {}
        order_specs = [
            ("boda", "aurora", "Boda García-López", "Hacienda San Ángel", 8,
             [("chair", 10), ("table", 2), ("speaker", 2), ("light", 4)]),
            ("gala", "granvia", "Gala Hotel Gran Vía", "Salón Imperial", 12,
             [("floor", 1), ("light", 4), ("speaker", 2)]),
        ]
        for okey, pk, ev, loc, day, lines in order_specs:
            order = SaleOrder.create({
                "partner_id": partners[pk].id,
                "x_is_event_rental": True,
                "x_event_name": ev, "x_event_location": loc,
                "x_event_start": self._at(day, 10), "x_event_end": self._at(day, 23),
                "x_billable_start": self._at(day, 10), "x_billable_end": self._at(day, 23),
                "x_block_start": self._at(day - 2, 8), "x_block_end": self._at(day + 2, 18),
                "x_logistics_notes": "Montaje T-2, desmontaje T+1, revisión T+2.",
            })
            for prod, qty in lines:
                OrderLine.create({
                    "order_id": order.id, "product_id": products[prod].id,
                    "product_uom_qty": qty,
                    "x_billable_start": self._at(day, 10), "x_billable_end": self._at(day, 23),
                    "x_block_start": self._at(day - 2, 8), "x_block_end": self._at(day + 2, 18),
                })
            orders[okey] = order

        # --- Reservations across all states (no overlap via availability) ---
        self._resv(products["chair"], 3, partners["aurora"], "released", -22, 8, -15, 18, policy="on_block_end")
        self._resv(products["table"], 1, partners["granvia"], "returned", -4, 8, -1, 18)
        self._resv(products["floor"], 1, partners["granvia"], "in_use", -1, 8, 3, 18, so=orders["gala"])
        self._resv(products["chair"], 10, partners["aurora"], "prepared", 6, 8, 10, 18, so=orders["boda"], bill=(8, 10, 23))
        self._resv(products["light"], 4, partners["aurora"], "reserved", 6, 8, 10, 18, so=orders["boda"])
        self._resv(products["speaker"], 2, partners["granvia"], "picked_up", 1, 8, 5, 18, so=orders["gala"])
        self._resv(products["light"], 3, partners["luna"], "soft_hold", 9, 8, 14, 18, policy="manual_only", soft_hours=2)
        self._resv(products["chair"], 2, partners["luna"], "quotation", 20, 8, 25, 18)
        self._resv(products["projector"], 1, partners["cumbre"], "draft", 22, 8, 27, 18)

        # --- Downtime ---
        Downtime = self.env["rental.serial.downtime"]
        Downtime.create({
            "lot_id": serials["speaker"][5].id, "reason": "maintenance",
            "state": "scheduled", "start_datetime": self._at(-2, 8),
            "end_datetime": self._at(3, 18), "notes": "Revisión de bocina post-evento"})
        Downtime.create({
            "lot_id": serials["chair"][19].id, "reason": "damaged",
            "state": "in_progress", "start_datetime": self._at(-5, 8),
            "notes": "Pata rota, fuera de servicio."})
        Downtime.create({
            "lot_id": serials["mic"][7].id, "reason": "lost",
            "state": "in_progress", "start_datetime": self._at(-10, 8),
            "notes": "Extraviado en evento, en investigación."})

        # --- Confirmed orders with real serial pickings (staggered dates) ---
        self._confirmed_order(products, partners, "Congreso Médico Anual", "zenith",
                              "Expo Center", -12, -15, -9,
                              [("mic", 2), ("screen", 1)], "closed")
        self._confirmed_order(products, partners, "Festival Gastronómico", "luna",
                              "Parque Central", 0, -2, 3,
                              [("heater", 2), ("table", 1)], "ongoing")
        self._confirmed_order(products, partners, "Lanzamiento de Producto", "cumbre",
                              "Showroom Cumbre", 18, 16, 20,
                              [("projector", 1), ("mic", 2)], "future")

    # ------------------------------------------------------------------
    def _resv(self, product, qty, partner, state, d1, h1, d2, h2,
              policy="on_return_validation", so=None, soft_hours=None, bill=None):
        svc = self.env["rental.availability.service"]
        Res = self.env["rental.serial.reservation"]
        start, end = self._at(d1, h1), self._at(d2, h2)
        available = svc.get_available_serials(product.id, start, end)
        for lot in available[:qty]:
            vals = {
                "partner_id": partner.id,
                "product_id": product.id,
                "lot_id": lot.id,
                "company_id": self.env.company.id,
                "state": state,
                "auto_release_policy": policy,
                "reservation_block_start": start,
                "reservation_block_end": end,
            }
            if so:
                vals["sale_order_id"] = so.id
            if bill:
                bd, bh1, bh2 = bill
                vals["rental_billable_start"] = self._at(bd, bh1)
                vals["rental_billable_end"] = self._at(bd, bh2)
            if soft_hours is not None:
                vals["soft_hold_until"] = datetime.now() + timedelta(hours=soft_hours)
                vals["soft_hold_owner_id"] = self.env.uid
                vals["soft_hold_reason"] = "Apartado mientras el cliente confirma"
            Res.create(vals)

    def _confirmed_order(self, products, partners, name, pk, loc, ev, bf, bt,
                         items, lifecycle):
        try:
            with self.env.cr.savepoint():
                wh = self.env["stock.warehouse"].search(
                    [("company_id", "=", self.env.company.id)], limit=1)
                stock_loc = wh.lot_stock_id
                svc = self.env["rental.availability.service"]
                Res = self.env["rental.serial.reservation"]
                order = self.env["sale.order"].create({
                    "partner_id": partners[pk].id,
                    "x_is_event_rental": True, "x_event_name": name,
                    "x_event_location": loc,
                    "x_event_start": self._at(ev, 10), "x_event_end": self._at(ev, 23),
                    "x_billable_start": self._at(ev, 10), "x_billable_end": self._at(ev, 23),
                    "x_block_start": self._at(bf, 8), "x_block_end": self._at(bt, 18),
                })
                reservations = Res
                for prod_key, qty in items:
                    product = products[prod_key]
                    line = self.env["sale.order.line"].create({
                        "order_id": order.id, "product_id": product.id,
                        "product_uom_qty": qty,
                        "x_billable_start": self._at(ev, 10), "x_billable_end": self._at(ev, 23),
                        "x_block_start": self._at(bf, 8), "x_block_end": self._at(bt, 18),
                    })
                    available = svc.get_available_serials(
                        product.id, self._at(bf, 8), self._at(bt, 18), stock_loc.id)
                    for lot in available[:qty]:
                        reservations |= Res.create({
                            "sale_order_id": order.id, "sale_order_line_id": line.id,
                            "partner_id": partners[pk].id, "product_id": product.id,
                            "lot_id": lot.id, "warehouse_id": wh.id,
                            "location_id": stock_loc.id, "company_id": self.env.company.id,
                            "rental_billable_start": self._at(ev, 10),
                            "rental_billable_end": self._at(ev, 23),
                            "reservation_block_start": self._at(bf, 8),
                            "reservation_block_end": self._at(bt, 18),
                            "state": "reserved",
                        })
                if lifecycle == "closed":
                    reservations.action_create_delivery_picking()
                    reservations.action_create_return_picking()
                    reservations.action_release()
                elif lifecycle == "ongoing":
                    reservations.action_create_delivery_picking()
                    reservations.write({"state": "in_use"})
                try:
                    with self.env.cr.savepoint():
                        order.write({"state": "sale"})
                except Exception:
                    pass
        except Exception:
            # A picking-path incompatibility must not abort the whole loader.
            pass
