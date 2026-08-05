from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from ecommerce_disputes.agents import PolicyAgent
from ecommerce_disputes.models import DeliveryFinding, Item, Order, OrderFinding, Payment, PaymentFinding


OID = "a" * 32
SID = "b" * 32
DATE = datetime(2018, 1, 1)


def findings(
    *,
    status: str = "delivered",
    late: bool = False,
    seller_late: bool = False,
    payments: int = 1,
    reconciled: bool = True,
    payment_total: str = "115.00",
) -> tuple[OrderFinding, PaymentFinding, DeliveryFinding]:
    item = Item(OID, 1, SID, DATE, Decimal("100.00"), Decimal("15.00"))
    order = Order(OID, status, DATE, DATE, DATE)
    order_finding = OrderFinding(order, (item,), (item,) if seller_late else ())
    payment_rows = tuple(
        Payment(OID, index + 1, Decimal(payment_total) / payments)
        for index in range(payments)
    )
    payment_finding = PaymentFinding(
        payment_rows,
        Decimal("100.00"),
        Decimal("15.00"),
        Decimal(payment_total),
        reconciled,
    )
    return order_finding, payment_finding, DeliveryFinding(late)


class PolicyAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PolicyAgent()

    def issue(self, **kwargs) -> str:
        return self.agent.decide(*findings(**kwargs)).primary_issue

    def test_all_six_policy_branches(self) -> None:
        self.assertEqual(self.issue(status="canceled"), "canceled_order_paid")
        self.assertEqual(self.issue(status="unavailable"), "unavailable_order_paid")
        self.assertEqual(self.issue(late=True, seller_late=True), "late_delivery_seller")
        self.assertEqual(self.issue(late=True), "late_delivery_logistics")
        self.assertEqual(self.issue(payments=2), "valid_split_payment")
        self.assertEqual(self.issue(), "unsupported_late_claim")

    def test_canceled_priority_beats_late_delivery(self) -> None:
        self.assertEqual(
            self.issue(status="canceled", late=True, seller_late=True, payments=2),
            "canceled_order_paid",
        )

    def test_split_payment_priority_beats_unsupported_claim(self) -> None:
        self.assertEqual(self.issue(payments=2), "valid_split_payment")

    def test_unmatched_case_fails_instead_of_hallucinating(self) -> None:
        with self.assertRaises(ValueError):
            self.agent.decide(*findings(reconciled=False, payment_total="120.00"))


if __name__ == "__main__":
    unittest.main()
