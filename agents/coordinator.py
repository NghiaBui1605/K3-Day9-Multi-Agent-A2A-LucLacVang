"""
Coordinator Agent
Responsibility: Orchestrate the full pipeline for a single case.
Dispatches to specialist agents, collects evidence, assembles final output,
and hands off to VerifierAgent for validation and file writing.

Flow:
  Input case → OrderSellerAgent → PaymentAgent → DeliveryAgent
             → PolicyAgent → [assemble output] → VerifierAgent → output/EC_XXX.json
"""

import logging
import time
from typing import Any

from agents.order_seller_agent import OrderSellerAgent
from agents.payment_agent import PaymentAgent
from agents.delivery_agent import DeliveryAgent
from agents.policy_agent import PolicyAgent
from agents.verifier_agent import VerifierAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """
    Coordinates the full dispute resolution pipeline for one case.
    Returns a trace dict with all intermediate results.
    """

    name = "CoordinatorAgent"

    def __init__(self):
        self.order_seller = OrderSellerAgent()
        self.payment = PaymentAgent()
        self.delivery = DeliveryAgent()
        self.policy = PolicyAgent()
        self.verifier = VerifierAgent()

    def run(self, case: dict) -> dict:
        """
        Process a single case end-to-end.
        Returns trace dict (for trace.jsonl).
        """
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        start_time = time.time()

        logger.info(f"[{self.name}] ===== Starting case {case_id} | order={order_id} =====")

        trace: dict[str, Any] = {
            "case_id": case_id,
            "order_id": order_id,
            "opened_at": case.get("opened_at"),
            "customer_message": case["customer_request"].get("message", ""),
            "steps": [],
            "warnings": [],
            "elapsed_s": 0,
        }

        # ── Step 1: Order & Seller Agent ──────────────────────────────────────
        t0 = time.time()
        order_facts = self.order_seller.run(case)
        trace["steps"].append({
            "agent": "OrderSellerAgent",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "result_summary": {
                "found": order_facts.get("found"),
                "order_status": order_facts.get("order_status"),
                "item_count": order_facts.get("item_count", 0),
                "seller_ids": order_facts.get("seller_ids", []),
            },
        })

        # ── Step 2: Payment Agent ──────────────────────────────────────────────
        t0 = time.time()
        payment_facts = self.payment.run(order_facts)
        trace["steps"].append({
            "agent": "PaymentAgent",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "result_summary": {
                "total_payment_brl": payment_facts.get("total_payment_brl"),
                "is_split_payment": payment_facts.get("is_split_payment"),
                "payment_reconciled": payment_facts.get("payment_reconciled"),
            },
        })

        # ── Step 3: Delivery Agent ─────────────────────────────────────────────
        t0 = time.time()
        delivery_facts = self.delivery.run(order_facts)
        trace["steps"].append({
            "agent": "DeliveryAgent",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "result_summary": {
                "delivered_late": delivery_facts.get("delivered_late"),
                "days_late": delivery_facts.get("days_late"),
                "seller_handoff_late": delivery_facts.get("seller_handoff_late"),
                "late_seller_ids": delivery_facts.get("late_seller_ids", []),
            },
        })

        # ── Step 4: Policy Agent ───────────────────────────────────────────────
        t0 = time.time()
        policy_decision = self.policy.run(order_facts, payment_facts, delivery_facts)
        trace["steps"].append({
            "agent": "PolicyAgent",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "result_summary": {
                "primary_issue": policy_decision.get("primary_issue"),
                "action": policy_decision.get("action"),
                "refund_brl": policy_decision.get("recommended_refund_brl"),
                "confidence": policy_decision.get("confidence"),
            },
        })

        # ── Assemble output JSON ───────────────────────────────────────────────
        output = self._assemble_output(
            case_id, order_id,
            order_facts, payment_facts, delivery_facts, policy_decision
        )

        # ── Step 5: Verifier Agent ─────────────────────────────────────────────
        t0 = time.time()
        validated_output, warnings = self.verifier.run(case_id, output)
        trace["steps"].append({
            "agent": "VerifierAgent",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "result_summary": {
                "warnings_count": len(warnings),
                "warnings": warnings,
            },
        })

        trace["warnings"] = warnings
        trace["final_output"] = validated_output
        trace["elapsed_s"] = round(time.time() - start_time, 3)

        logger.info(
            f"[{self.name}] ===== Done {case_id} | "
            f"{policy_decision.get('primary_issue')} | "
            f"refund={policy_decision.get('recommended_refund_brl')} BRL | "
            f"{trace['elapsed_s']}s ====="
        )

        return trace

    # ──────────────────────────────────────────────────────────────────────────
    def _assemble_output(
        self,
        case_id: str,
        order_id: str,
        order_facts: dict,
        payment_facts: dict,
        delivery_facts: dict,
        policy_decision: dict,
    ) -> dict:
        """Build the final output JSON matching the required schema."""

        items = order_facts.get("items", [])
        seller_ids = order_facts.get("seller_ids", [])
        payments = payment_facts.get("payment_rows", [])
        primary_issue = policy_decision.get("primary_issue", "unsupported_late_claim")
        root_cause = policy_decision.get("root_cause_code", "DELIVERY_WITHIN_ESTIMATE")

        # --- Affected entities ---
        item_ids = [
            f"{order_id}:{item['order_item_id']}"
            for item in items
            if item.get("order_item_id") is not None
        ][:5]

        payment_ids = [
            f"{order_id}:{p['payment_sequential']}"
            for p in payments
            if p.get("payment_sequential") is not None
        ][:5]

        # --- Evidence IDs ---
        evidence_ids = []
        evidence_ids.append(f"order:{order_id}")
        for eid in item_ids[:3]:
            evidence_ids.append(f"item:{eid}")
        for pid in payment_ids[:2]:
            evidence_ids.append(f"payment:{pid}")
        for sid in seller_ids[:2]:
            evidence_ids.append(f"seller:{sid}")
        evidence_ids.append(f"policy:{root_cause}")

        # Handle no-item orders
        if not items:
            item_ids = []
            seller_ids_out = []
            item_total = 0.0
            freight_total = 0.0
        else:
            seller_ids_out = seller_ids[:5]
            item_total = payment_facts.get("item_total_brl", 0.0)
            freight_total = payment_facts.get("freight_total_brl", 0.0)

        return {
            "case_id": case_id,
            "assessment": {
                "primary_issue": primary_issue,
                "case_status": policy_decision.get("case_status", "no_action"),
                "confidence": policy_decision.get("confidence", 0.8),
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids_out,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": policy_decision.get("ranked_causes", [
                    {"cause_code": root_cause, "rank": 1}
                ]),
                "responsible_parties": policy_decision.get("responsible_parties", []),
            },
            "evidence_ids": evidence_ids[:10],
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": round(item_total, 2),
                "freight_total_brl": round(freight_total, 2),
                "payment_total_brl": round(payment_facts.get("total_payment_brl", 0.0), 2),
                "recommended_refund_brl": round(
                    policy_decision.get("recommended_refund_brl", 0.0), 2
                ),
            },
            "resolution_actions": [policy_decision.get("action", "reject_late_refund")],
        }
