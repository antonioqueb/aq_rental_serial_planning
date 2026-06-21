{
    "name": "AQ Rental Serial Planning",
    "version": "19.0.1.2.0",
    "category": "Sales/Rental",
    "summary": "Booqable-style serial-level rental planning, availability engine and "
               "timeline calendar on top of native Odoo Rental.",
    "description": """
AQ Rental Serial Planning
=========================

Adds a serial-number based reservation layer on top of the native Odoo Rental
application (``sale_renting``):

* Reserve specific ``stock.lot`` units instead of generic quantities.
* Separate *billable period* (what the customer pays) from the *operational
  block period* (what really blocks inventory: prep, delivery, use, pickup,
  cleaning, review).
* No double booking of the same serial on overlapping operational periods
  (enforced both at ORM level and with a PostgreSQL ``EXCLUDE`` constraint).
* Rental packages/bundles that explode into serial-tracked components.
* Availability engine per product / per serial / per package.
* Soft holds with automatic expiry, configurable auto-release policies.
* Downtime (maintenance / damage / lost) blocking availability.
* OWL timeline board (Booqable-like) with one row per serial.
""",
    "author": "AlphaQueb",
    "website": "https://alphaqueb.com",
    "license": "LGPL-3",
    "depends": [
        "sale_renting",
        "stock",
        "account",
        "web",
    ],
    "data": [
        "security/rental_security.xml",
        "security/ir.model.access.csv",
        "security/rental_record_rules.xml",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "wizard/rental_serial_assign_wizard_views.xml",
        "views/rental_serial_reservation_views.xml",
        "views/rental_package_views.xml",
        "views/rental_serial_downtime_views.xml",
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/stock_lot_views.xml",
        "views/rental_planning_board_views.xml",
        "views/rental_planning_menus.xml",
        "report/rental_logistics_report.xml",
    ],
    "demo": [
        "demo/aq_rental_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "aq_rental_serial_planning/static/src/planning/planning_board.scss",
            "aq_rental_serial_planning/static/src/planning/planning_board.xml",
            "aq_rental_serial_planning/static/src/planning/planning_board.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
