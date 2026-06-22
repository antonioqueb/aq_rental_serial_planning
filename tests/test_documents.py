# -*- coding: utf-8 -*-
import base64
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Cliente Doc"})
        cls.order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id, "x_is_event_rental": True,
            "x_event_name": "Boda demo"})
        cls.product = cls.env["product.product"].create({
            "name": "Bocina", "type": "consu", "tracking": "serial",
            "list_price": 100.0, "rent_ok": True, "x_rental_serial_planning": True})
        cls.lot = cls.env["stock.lot"].create({"name": "BOC-9", "product_id": cls.product.id})

    def test_contract_and_signature(self):
        """Case 7: generate a contract and mark it signed."""
        action = self.order.action_doc_contract()
        doc = self.env["rental.document.instance"].browse(action["res_id"])
        self.assertEqual(doc.document_type, "rental_contract")
        self.assertTrue(doc.template_id)
        doc.action_print()
        self.assertEqual(doc.state, "generated")
        doc.customer_signature = base64.b64encode(b"firma-cliente")
        doc.customer_signed_by = "Juan Pérez"
        doc.action_mark_signed()
        self.assertEqual(doc.state, "signed")
        self.assertTrue(doc.customer_signed_date)

    def test_damage_report_creates_charge(self):
        """Case 8: damage report -> suggested charge -> sale line + downtime."""
        reservation = self.env["rental.serial.reservation"].create({
            "product_id": self.product.id, "lot_id": self.lot.id,
            "partner_id": self.partner.id, "sale_order_id": self.order.id,
            "state": "returned",
            "reservation_block_start": datetime(2026, 9, 1, 8, 0),
            "reservation_block_end": datetime(2026, 9, 3, 18, 0)})
        report = self.env["rental.damage.report"].create({
            "reservation_id": reservation.id, "product_id": self.product.id,
            "lot_id": self.lot.id, "sale_order_id": self.order.id,
            "damage_type": "damage", "severity": "major",
            "replacement_value": 100.0, "quantity": 1.0})
        self.assertAlmostEqual(report.suggested_charge, 60.0, places=2)
        report.action_create_charge()
        self.assertEqual(report.state, "charged")
        self.assertTrue(report.charge_line_id)
        self.assertAlmostEqual(report.charge_line_id.price_unit, 60.0, places=2)
        self.assertTrue(report.downtime_id)
        self.assertEqual(report.downtime_id.lot_id, self.lot)
