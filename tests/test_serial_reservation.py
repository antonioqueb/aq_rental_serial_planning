# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError


class TestSerialReservation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["rental.serial.reservation"]
        cls.product = cls.env["product.product"].create({
            "name": "Sillas Manhattan",
            "type": "consu",
            "tracking": "serial",
            "rent_ok": True,
            "x_rental_serial_planning": True,
            "x_requires_serial_reservation": True,
        })
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"SILLA-{i:03d}", "product_id": cls.product.id}
            for i in range(1, 6)
        ])
        cls.partner = cls.env["res.partner"].create({"name": "Event Co"})

    def _reservation(self, lot, start, end, state="reserved"):
        return self.Reservation.create({
            "product_id": self.product.id,
            "lot_id": lot.id,
            "partner_id": self.partner.id,
            "reservation_block_start": start,
            "reservation_block_end": end,
            "state": state,
        })

    def test_block_period_validation(self):
        start = datetime(2026, 7, 1, 10, 0)
        with self.assertRaises(Exception):
            self._reservation(self.lots[0], start, start - timedelta(hours=1))

    def test_overlap_same_serial_blocked(self):
        """Case: no double booking of the same serial on overlapping periods."""
        s1 = datetime(2026, 7, 2, 8, 0)
        e1 = datetime(2026, 7, 6, 18, 0)
        self._reservation(self.lots[0], s1, e1)
        with self.assertRaises(ValidationError):
            self._reservation(self.lots[0],
                              datetime(2026, 7, 4, 8, 0),
                              datetime(2026, 7, 8, 18, 0))

    def test_non_overlap_same_serial_ok(self):
        self._reservation(self.lots[0],
                          datetime(2026, 7, 2, 8, 0),
                          datetime(2026, 7, 6, 18, 0))
        # Touching at the boundary is allowed ([) semantics).
        r2 = self._reservation(self.lots[0],
                               datetime(2026, 7, 6, 18, 0),
                               datetime(2026, 7, 9, 18, 0))
        self.assertEqual(r2.conflict_status, "ok")

    def test_released_does_not_block(self):
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.write({"state": "released", "actual_return_datetime": datetime(2026, 7, 6)})
        # Same period now free for a new reservation.
        r2 = self._reservation(self.lots[0],
                               datetime(2026, 7, 3, 8, 0),
                               datetime(2026, 7, 5, 18, 0))
        self.assertEqual(r2.conflict_status, "ok")

    def test_change_serial(self):
        """Case 4: change of serial validates availability and frees the old one."""
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.action_change_serial(self.lots[1].id)
        self.assertEqual(r1.lot_id, self.lots[1])

    def test_release_requires_return_when_policy(self):
        r1 = self._reservation(self.lots[0],
                               datetime(2026, 7, 2, 8, 0),
                               datetime(2026, 7, 6, 18, 0))
        r1.auto_release_policy = "on_return_validation"
        with self.assertRaises(UserError):
            r1.action_release()
        r1.action_return()
        r1.action_release()
        self.assertEqual(r1.state, "released")
