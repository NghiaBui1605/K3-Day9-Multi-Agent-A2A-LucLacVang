from __future__ import annotations

import json
from pathlib import Path

from .agents import DeliveryAgent, OrderSellerAgent, PaymentAgent, PolicyAgent
from .models import CaseInput
from .repository import OlistRepository
from .settings import POLICY_VERSION
from .tracing import TraceWriter
from .verifier import VerifierAgent


class CoordinatorAgent:
    name = "coordinator_agent"

    def __init__(self, repository: OlistRepository, trace: TraceWriter):
        self.repository = repository
        self.trace = trace
        self.order_agent = OrderSellerAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()

    def process(self, case: CaseInput) -> dict:
        if case.policy_version != POLICY_VERSION:
            raise ValueError(f"Unsupported policy: {case.policy_version}")
        if not case.case_id or not case.claimed_order_id:
            raise ValueError("case_id and claimed_order_id are required")

        self.trace.emit(
            case.case_id,
            self.name,
            "case_received",
            {"order_id": case.claimed_order_id, "policy_version": case.policy_version},
        )
        order = self.order_agent.investigate(self.repository, case.claimed_order_id)
        self.trace.emit(
            case.case_id,
            self.order_agent.name,
            "handoff",
            {
                "to": self.name,
                "order_status": order.order.status,
                "item_count": len(order.items),
                "violating_seller_ids": list(order.violating_seller_ids),
            },
        )
        payment = self.payment_agent.investigate(self.repository, case.claimed_order_id)
        self.trace.emit(
            case.case_id,
            self.payment_agent.name,
            "handoff",
            {
                "to": self.name,
                "payment_rows": len(payment.payments),
                "item_total_brl": float(payment.item_total),
                "freight_total_brl": float(payment.freight_total),
                "payment_total_brl": float(payment.payment_total),
                "reconciled": payment.reconciled,
            },
        )
        delivery = self.delivery_agent.investigate(order)
        self.trace.emit(
            case.case_id,
            self.delivery_agent.name,
            "handoff",
            {"to": self.name, "delivered_late": delivery.delivered_late},
        )
        decision = self.policy_agent.decide(order, payment, delivery)
        self.trace.emit(
            case.case_id,
            self.policy_agent.name,
            "handoff",
            {
                "to": self.verifier_agent.name,
                "primary_issue": decision.primary_issue,
                "root_cause": decision.root_cause,
                "refund_brl": float(decision.refund),
                "action": decision.action,
            },
        )
        result = self.verifier_agent.assemble(case, order, payment, delivery, decision)
        self.trace.emit(
            case.case_id,
            self.verifier_agent.name,
            "verification_passed",
            {"evidence_count": len(result["evidence_ids"]), "schema_valid": True},
        )
        return result


def load_cases(input_dir: Path) -> list[tuple[Path, CaseInput]]:
    files = sorted(input_dir.glob("EC_*.json"))
    cases: list[tuple[Path, CaseInput]] = []
    for path in files:
        with path.open("r", encoding="utf-8-sig") as handle:
            cases.append((path, CaseInput.from_json(json.load(handle))))
    return cases
