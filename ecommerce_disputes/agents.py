from __future__ import annotations

from decimal import Decimal
from typing import Any

from .llm import OpenAILLMClient
from .models import (
    Decision,
    DeliveryFinding,
    OrderFinding,
    PaymentFinding,
    ZERO,
    money,
)
from .repository import OlistRepository
from .settings import PAYMENT_TOLERANCE_BRL


class OrderSellerAgent:
    name = "order_seller_agent"

    def investigate(self, repository: OlistRepository, order_id: str) -> OrderFinding:
        order = repository.order(order_id)
        items = repository.order_items(order_id)
        violating = tuple(
            item
            for item in items
            if order.delivered_carrier_at is not None
            and order.delivered_carrier_at > item.shipping_limit_at
        )
        return OrderFinding(order=order, items=items, violating_items=violating)


class PaymentAgent:
    name = "payment_agent"

    def investigate(self, repository: OlistRepository, order_id: str) -> PaymentFinding:
        items = repository.order_items(order_id)
        payments = repository.order_payments(order_id)
        item_total = money(sum((item.price for item in items), ZERO))
        freight_total = money(sum((item.freight for item in items), ZERO))
        payment_total = money(sum((payment.value for payment in payments), ZERO))
        difference = abs(payment_total - item_total - freight_total)
        return PaymentFinding(
            payments=payments,
            item_total=item_total,
            freight_total=freight_total,
            payment_total=payment_total,
            reconciled=difference <= Decimal(PAYMENT_TOLERANCE_BRL),
        )


class DeliveryAgent:
    name = "delivery_agent"

    def investigate(self, order_finding: OrderFinding) -> DeliveryFinding:
        order = order_finding.order
        delivered_late = (
            order.delivered_customer_at is not None
            and order.estimated_delivery_at is not None
            and order.delivered_customer_at > order.estimated_delivery_at
        )
        return DeliveryFinding(delivered_late=delivered_late)


class PolicyAgent:
    name = "policy_agent"

    def __init__(self, llm: OpenAILLMClient | None = None):
        self.llm = llm
        self.last_model_output: dict[str, Any] | None = None

    def decide(
        self,
        order: OrderFinding,
        payment: PaymentFinding,
        delivery: DeliveryFinding,
    ) -> Decision:
        expected = self._rule_decision(order, payment, delivery)
        if self.llm is None:
            return expected

        facts = {
            "order_status": order.order.status,
            "delivered_late": delivery.delivered_late,
            "violating_seller_ids": list(order.violating_seller_ids),
            "payment_row_count": len(payment.payments),
            "item_total_brl": float(payment.item_total),
            "freight_total_brl": float(payment.freight_total),
            "payment_total_brl": float(payment.payment_total),
            "payment_reconciled_within_0_10_brl": payment.reconciled,
        }
        system = (
            "You are the EC_POLICY_V1 Policy Agent. Classify only from the supplied facts. "
            "Apply these rules in exact priority order: (1) canceled and paid => "
            "canceled_order_paid; (2) unavailable and paid => unavailable_order_paid; "
            "(3) delivered late with any violating seller => late_delivery_seller; "
            "(4) delivered late without a violating seller => late_delivery_logistics; "
            "(5) at least two payment rows and reconciled => valid_split_payment; "
            "(6) not delivered late and reconciled => unsupported_late_claim. "
            "Return JSON only with primary_issue and a short rationale. Never invent facts."
        )
        proposal = self.llm.json_completion(system, facts)
        self.last_model_output = proposal
        if proposal.get("primary_issue") != expected.primary_issue:
            raise ValueError(
                "Verifier rejected LLM policy proposal: "
                f"{proposal.get('primary_issue')!r} != {expected.primary_issue!r}"
            )
        return expected

    def _rule_decision(
        self,
        order: OrderFinding,
        payment: PaymentFinding,
        delivery: DeliveryFinding,
    ) -> Decision:
        # The branch order is part of EC_POLICY_V1 and must not be rearranged.
        if order.order.status == "canceled" and payment.payment_total > ZERO:
            return Decision(
                "canceled_order_paid",
                "ORDER_CANCELED_AFTER_PAYMENT",
                (("platform", "OLIST_PLATFORM"),),
                payment.payment_total,
                "issue_full_refund",
            )
        if order.order.status == "unavailable" and payment.payment_total > ZERO:
            return Decision(
                "unavailable_order_paid",
                "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                (("platform", "OLIST_PLATFORM"),),
                payment.payment_total,
                "issue_full_refund",
            )
        if delivery.delivered_late and order.violating_seller_ids:
            return Decision(
                "late_delivery_seller",
                "SELLER_HANDOFF_AFTER_LIMIT",
                tuple(("seller", seller_id) for seller_id in order.violating_seller_ids[:3]),
                payment.freight_total,
                "refund_freight",
            )
        if delivery.delivered_late and not order.violating_seller_ids:
            return Decision(
                "late_delivery_logistics",
                "CARRIER_DELIVERED_AFTER_ESTIMATE",
                (("logistics_provider", "LOGISTICS_PROVIDER"),),
                payment.freight_total,
                "refund_freight",
            )
        if len(payment.payments) >= 2 and payment.reconciled:
            return Decision(
                "valid_split_payment",
                "MULTIPLE_PAYMENTS_RECONCILED",
                (),
                ZERO,
                "explain_valid_split_payment",
            )
        if not delivery.delivered_late and payment.reconciled:
            return Decision(
                "unsupported_late_claim",
                "DELIVERY_WITHIN_ESTIMATE",
                (),
                ZERO,
                "reject_late_refund",
            )
        raise ValueError(
            f"Order {order.order.order_id} does not match any EC_POLICY_V1 branch"
        )
