# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class TestSerialSubstitution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create({
            "name": "Bocina JBL", "type": "consu", "is_storable": True,
            "tracking": "serial", "rent_ok": True,
            "x_rental_serial_planning": True})
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"BOC-{i:03d}", "product_id": cls.product.id} for i in range(1, 4)])
        for lot in cls.lots:
            cls.env["stock.quant"].create({
                "product_id": cls.product.id, "lot_id": lot.id,
                "location_id": cls.stock_loc.id, "quantity": 1.0})
        cls.partner = cls.env["res.partner"].create({"name": "Evento X"})
        cls.start = datetime(2026, 9, 5, 8, 0)
        cls.end = datetime(2026, 9, 9, 18, 0)
        cls.reservation = cls.env["rental.serial.reservation"].create({
            "product_id": cls.product.id, "lot_id": cls.lots[0].id,
            "partner_id": cls.partner.id, "state": "reserved",
            "reservation_block_start": cls.start, "reservation_block_end": cls.end})

    def test_substitute_creates_log_and_downtime(self):
        """Case 4: substitute a committed serial, log it, block the old one."""
        wizard = self.env["rental.serial.substitution.wizard"].with_context(
            active_id=self.reservation.id).create({})
        # the old lot must not be offered, the others must be available
        self.assertNotIn(self.lots[0], wizard.available_lot_ids)
        self.assertIn(self.lots[1], wizard.available_lot_ids)

        wizard.new_lot_id = self.lots[1]
        wizard.reason = "damaged"
        wizard.create_downtime_for_old_lot = True
        wizard.downtime_reason = "damaged"
        wizard.action_substitute()

        self.assertEqual(self.reservation.lot_id, self.lots[1])
        log = self.env["rental.serial.substitution.log"].search(
            [("reservation_id", "=", self.reservation.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.old_lot_id, self.lots[0])
        self.assertEqual(log.new_lot_id, self.lots[1])
        self.assertTrue(log.old_downtime_id)
        # old serial is now blocked by downtime -> unavailable
        avail = self.env["rental.availability.service"].get_available_serials(
            self.product.id, self.start, self.end)
        self.assertNotIn(self.lots[0], avail)

    def test_cannot_substitute_with_blocked_serial(self):
        """A serial already reserved overlapping cannot be chosen."""
        self.env["rental.serial.reservation"].create({
            "product_id": self.product.id, "lot_id": self.lots[1].id,
            "partner_id": self.partner.id, "state": "reserved",
            "reservation_block_start": self.start, "reservation_block_end": self.end})
        wizard = self.env["rental.serial.substitution.wizard"].with_context(
            active_id=self.reservation.id).create({})
        # lots[1] is busy in the same period -> only lots[2] free
        self.assertNotIn(self.lots[1], wizard.available_lot_ids)
        self.assertIn(self.lots[2], wizard.available_lot_ids)
