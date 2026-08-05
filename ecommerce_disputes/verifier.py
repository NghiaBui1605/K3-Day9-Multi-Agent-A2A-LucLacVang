from __future__ import annotations

import re
from typing import Any

from .models import CaseInput, Decision, DeliveryFinding, OrderFinding, PaymentFinding, money
from .repository import OlistRepository
from .settings import CONFIDENCE


ISSUE_ACTION = {
    "canceled_order_paid": "issue_full_refund",
    "unavailable_order_paid": "issue_full_refund",
    "late_delivery_seller": "refund_freight",
    "late_delivery_logistics": "refund_freight",
    "valid_split_payment": "explain_valid_split_payment",
    "unsupported_late_claim": "reject_late_refund",
}
EVIDENCE_PATTERN = re.compile(
    r"^(order:[0-9a-f]{32}|item:[0-9a-f]{32}:\d+|payment:[0-9a-f]{32}:\d+|seller:[0-9a-f]{32}|policy:[A-Z_]+)$"
)


class VerifierAgent:
    name = "verifier_agent"

    def assemble(
        self,
        case: CaseInput,
        order: OrderFinding,
        payment: PaymentFinding,
        delivery: DeliveryFinding,
        decision: Decision,
    ) -> dict[str, Any]:
        order_id = order.order.order_id
        item_ids = [f"{order_id}:{item.item_id}" for item in order.items[:5]]
        seller_ids = list(order.seller_ids[:5])
        payment_ids = [f"{order_id}:{p.sequential}" for p in payment.payments[:5]]

        evidence = [f"order:{order_id}"]
        evidence.extend(f"item:{item_id}" for item_id in item_ids)
        evidence.extend(f"payment:{payment_id}" for payment_id in payment_ids)
        evidence.extend(f"seller:{seller_id}" for seller_id in seller_ids)
        evidence.append(f"policy:{decision.root_cause}")
        if len(evidence) > 10:
            evidence = evidence[:9] + [f"policy:{decision.root_cause}"]

        result = {
            "case_id": case.case_id,
            "assessment": {
                "primary_issue": decision.primary_issue,
                "case_status": "action_required" if decision.refund > 0 else "no_action",
                "confidence": CONFIDENCE,
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": decision.root_cause, "rank": 1}],
                "responsible_parties": [
                    {"party_type": party_type, "party_id": party_id}
                    for party_type, party_id in decision.responsible_parties
                ],
            },
            "evidence_ids": evidence,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": float(payment.item_total),
                "freight_total_brl": float(payment.freight_total),
                "payment_total_brl": float(payment.payment_total),
                "recommended_refund_brl": float(money(decision.refund)),
            },
            "resolution_actions": [decision.action],
        }
        self.validate(result, case, order, payment, delivery, decision)
        return result

    def validate(
        self,
        result: dict[str, Any],
        case: CaseInput,
        order: OrderFinding,
        payment: PaymentFinding,
        delivery: DeliveryFinding,
        decision: Decision,
    ) -> None:
        if result["case_id"] != case.case_id:
            raise ValueError("case_id mismatch")
        assessment = result["assessment"]
        if not 0 <= assessment["confidence"] <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if ISSUE_ACTION.get(assessment["primary_issue"]) != result["resolution_actions"][0]:
            raise ValueError("issue/action mismatch")
        if assessment["case_status"] != ("action_required" if decision.refund > 0 else "no_action"):
            raise ValueError("case status/refund mismatch")

        entities = result["affected_entities"]
        for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            if len(entities[key]) > 5 or len(entities[key]) != len(set(entities[key])):
                raise ValueError(f"invalid affected entity set: {key}")
        if len(result["evidence_ids"]) > 10:
            raise ValueError("too many evidence IDs")
        if len(result["root_cause_analysis"]["ranked_causes"]) > 3:
            raise ValueError("too many root causes")
        if len(result["root_cause_analysis"]["responsible_parties"]) > 3:
            raise ValueError("too many responsible parties")
        if len(result["resolution_actions"]) > 5:
            raise ValueError("too many actions")

        valid_evidence = {f"order:{order.order.order_id}", f"policy:{decision.root_cause}"}
        valid_evidence.update(
            f"item:{item.order_id}:{item.item_id}" for item in order.items
        )
        valid_evidence.update(
            f"payment:{p.order_id}:{p.sequential}" for p in payment.payments
        )
        valid_evidence.update(f"seller:{seller_id}" for seller_id in order.seller_ids)
        for evidence_id in result["evidence_ids"]:
            if not EVIDENCE_PATTERN.fullmatch(evidence_id) or evidence_id not in valid_evidence:
                raise ValueError(f"invalid evidence ID: {evidence_id}")

        financial = result["financial_resolution"]
        expected = (
            payment.item_total,
            payment.freight_total,
            payment.payment_total,
            money(decision.refund),
        )
        actual = tuple(
            money(financial[key])
            for key in (
                "item_total_brl",
                "freight_total_brl",
                "payment_total_brl",
                "recommended_refund_brl",
            )
        )
        if actual != expected:
            raise ValueError(f"financial mismatch: {actual} != {expected}")

    def validate_external(self, result: dict[str, Any], repository: OlistRepository) -> None:
        """Validate a saved result without trusting any previously held findings."""
        order_id = result["affected_entities"]["order_ids"][0]
        order = repository.order(order_id)
        items = repository.order_items(order_id)
        payments = repository.order_payments(order_id)
        valid = {f"order:{order.order_id}"}
        valid.update(f"item:{i.order_id}:{i.item_id}" for i in items)
        valid.update(f"payment:{p.order_id}:{p.sequential}" for p in payments)
        valid.update(f"seller:{i.seller_id}" for i in items)
        root = result["root_cause_analysis"]["ranked_causes"][0]["cause_code"]
        valid.add(f"policy:{root}")
        for evidence_id in result["evidence_ids"]:
            if evidence_id not in valid:
                raise ValueError(f"saved output has nonexistent evidence: {evidence_id}")
