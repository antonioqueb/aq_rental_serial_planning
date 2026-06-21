import logging
from datetime import datetime, timedelta

from . import models
from . import wizard
from . import controllers

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Build confirmed event orders with staggered dates that trigger real
    serial pickings (Section 12). Runs only when demo data is installed and is
    fully isolated so it can never break the module installation.
    """
    if not env.ref("aq_rental_serial_planning.so_boda", raise_if_not_found=False):
        return  # demo not loaded -> nothing to enrich

    now = datetime.now()
    wh = env["stock.warehouse"].search(
        [("company_id", "=", env.company.id)], limit=1)
    if not wh:
        return
    stock_loc = wh.lot_stock_id

    def at(day, hour):
        return (now + timedelta(days=day)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

    # name, partner_xmlid, location, event_day, block_from, block_to,
    # items [(product_xmlid, qty)], lifecycle
    SPECS = [
        ("Congreso Medico Anual", "partner_zenith", "Expo Center", -12, -15, -9,
         [("prod_mic", 2), ("prod_screen", 1)], "closed"),
        ("Festival Gastronomico", "partner_luna", "Parque Central", 0, -2, 3,
         [("prod_heater", 2), ("prod_table", 1)], "ongoing"),
        ("Lanzamiento de Producto", "partner_cumbre", "Showroom Cumbre", 18, 16, 20,
         [("prod_projector", 1), ("prod_mic", 2)], "future"),
    ]

    service = env["rental.availability.service"]
    SaleOrder = env["sale.order"]
    OrderLine = env["sale.order.line"]
    Reservation = env["rental.serial.reservation"]

    for name, partner_x, loc, ev, bf, bt, items, lifecycle in SPECS:
        try:
            with env.cr.savepoint():
                partner = env.ref(f"aq_rental_serial_planning.{partner_x}")
                order = SaleOrder.create({
                    "partner_id": partner.id,
                    "x_is_event_rental": True,
                    "x_event_name": name,
                    "x_event_location": loc,
                    "x_event_start": at(ev, 10), "x_event_end": at(ev, 23),
                    "x_billable_start": at(ev, 10), "x_billable_end": at(ev, 23),
                    "x_block_start": at(bf, 8), "x_block_end": at(bt, 18),
                    "x_logistics_notes": "Montaje, entrega, uso y retorno escalonados.",
                })
                reservations = Reservation.browse()
                for prod_x, qty in items:
                    product = env.ref(f"aq_rental_serial_planning.{prod_x}")
                    line = OrderLine.create({
                        "order_id": order.id,
                        "product_id": product.id,
                        "product_uom_qty": qty,
                        "x_billable_start": at(ev, 10), "x_billable_end": at(ev, 23),
                        "x_block_start": at(bf, 8), "x_block_end": at(bt, 18),
                    })
                    available = service.get_available_serials(
                        product.id, at(bf, 8), at(bt, 18), stock_loc.id)
                    for lot in available[:qty]:
                        reservations |= Reservation.create({
                            "sale_order_id": order.id,
                            "sale_order_line_id": line.id,
                            "partner_id": partner.id,
                            "product_id": product.id,
                            "lot_id": lot.id,
                            "warehouse_id": wh.id,
                            "location_id": stock_loc.id,
                            "company_id": env.company.id,
                            "rental_billable_start": at(ev, 10),
                            "rental_billable_end": at(ev, 23),
                            "reservation_block_start": at(bf, 8),
                            "reservation_block_end": at(bt, 18),
                            "state": "reserved",
                        })

                # Drive the lifecycle with REAL pickings.
                if lifecycle == "closed":
                    reservations.action_create_delivery_picking()   # stock -> customer
                    reservations.action_create_return_picking()     # customer -> stock
                    reservations.action_release()
                elif lifecycle == "ongoing":
                    reservations.action_create_delivery_picking()
                    reservations.write({"state": "in_use"})
                # 'future' stays reserved (Create Delivery button available)

                # Mark the order as confirmed (no native auto-delivery noise).
                try:
                    with env.cr.savepoint():
                        order.write({"state": "sale"})
                except Exception:
                    pass

                _logger.info("Demo confirmed order built: %s (%d serials)",
                             name, len(reservations))
        except Exception as e:  # noqa: BLE001 - demo must never break install
            _logger.warning(
                "aq_rental_serial_planning: skipped confirmed demo '%s': %s",
                name, e)
