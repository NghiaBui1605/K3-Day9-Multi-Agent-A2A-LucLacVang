"""
Policy Agent – LLM-powered
Uses LLM to apply EC_POLICY_V1 rules based on accumulated facts and LLM reasoning
from upstream agents.
"""

import json
import logging
from typing import Any
from agents.llm_client import call_llm_json

logger = logging.getLogger(__name__)

ROOT_CAUSE_MAP = {
    "canceled_order_paid":      "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid":   "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller":     "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics":  "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment":      "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim":   "DELIVERY_WITHIN_ESTIMATE",
}

ACTION_MAP = {
    "canceled_order_paid":      "issue_full_refund",
    "unavailable_order_paid":   "issue_full_refund",
    "late_delivery_seller":     "refund_freight",
    "late_delivery_logistics":  "refund_freight",
    "valid_split_payment":      "explain_valid_split_payment",
    "unsupported_late_claim":   "reject_late_refund",
}

CASE_STATUS_MAP = {
    "canceled_order_paid":      "action_required",
    "unavailable_order_paid":   "action_required",
    "late_delivery_seller":     "action_required",
    "late_delivery_logistics":  "action_required",
    "valid_split_payment":      "no_action",
    "unsupported_late_claim":   "no_action",
}

SYSTEM_PROMPT = """You are a Policy Engine Agent for an e-commerce dispute system.
Your job is to apply EC_POLICY_V1 rules in strict priority order based on the provided facts.
Rules Priority:
1. canceled_order_paid (order canceled, total payment > 0)
2. unavailable_order_paid (order unavailable, total payment > 0)
3. late_delivery_seller (delivered late AND seller handed off late)
4. late_delivery_logistics (delivered late AND seller handed off on time)
5. valid_split_payment (2+ payment rows, total matched)
6. unsupported_late_claim (default if nothing else applies)

You must return ONLY a JSON object. No explanations outside the JSON."""


class PolicyAgent:
    name = "PolicyAgent"

    def run(self, order_facts: dict, payment_facts: dict, delivery_facts: dict) -> dict:
        order_id = order_facts["order_id"]
        logger.info(f"[{self.name}] Applying policy for: {order_id}")

        if not order_facts.get("found"):
            return self._fallback(order_id)

        # Build context for LLM
        policy_context = {
            "order_status": order_facts.get("order_status"),
            "total_payment_brl": payment_facts.get("total_payment_brl", 0.0),
            "is_split_payment": payment_facts.get("is_split_payment", False),
            "payment_reconciled": payment_facts.get("payment_reconciled", True),
            "delivered_late": delivery_facts.get("delivered_late"),
            "seller_handoff_late": delivery_facts.get("seller_handoff_late", False),
            "delivery_verdict_from_upstream": delivery_facts.get("llm_delivery_verdict", "unknown"),
        }

        user_prompt = f"""Based on the following facts, select the highest priority policy rule that applies.
Return a JSON object with EXACTLY these fields:
- "primary_issue": string (must be one of the 6 rules listed in the system prompt)
- "confidence": float between 0.0 and 1.0 (how confident you are in this rule matching)
- "reasoning": string (explain why this rule was selected over others)

Facts:
{json.dumps(policy_context, indent=2)}

Return ONLY a JSON object."""

        llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt, max_tokens=300)

        # Fallback to deterministic if LLM output is malformed
        primary_issue = llm_result.get("primary_issue")
        confidence = float(llm_result.get("confidence", 0.8))
        if primary_issue not in ROOT_CAUSE_MAP:
            logger.warning(f"[{self.name}] Invalid LLM primary_issue: {primary_issue}. Falling back to deterministic.")
            primary_issue, confidence = self._deterministic_fallback(policy_context)

        # Determine responsible party
        party_type = None
        party_id = None
        late_seller_ids = delivery_facts.get("late_seller_ids", [])
        
        if primary_issue in ("canceled_order_paid", "unavailable_order_paid"):
            party_type = "platform"
            party_id = "OLIST_PLATFORM"
        elif primary_issue == "late_delivery_seller":
            party_type = "seller"
            party_id = late_seller_ids[0] if late_seller_ids else "UNKNOWN_SELLER"
        elif primary_issue == "late_delivery_logistics":
            party_type = "logistics_provider"
            party_id = "LOGISTICS_PROVIDER"

        # Determine refund amount
        refund = 0.0
        if primary_issue in ("canceled_order_paid", "unavailable_order_paid"):
            refund = payment_facts.get("total_payment_brl", 0.0)
        elif primary_issue in ("late_delivery_seller", "late_delivery_logistics"):
            refund = payment_facts.get("freight_total_brl", 0.0)

        action = ACTION_MAP[primary_issue]
        case_status = CASE_STATUS_MAP[primary_issue]
        root_cause = ROOT_CAUSE_MAP[primary_issue]

        responsible_parties = []
        if party_type and party_id:
            responsible_parties.append({"party_type": party_type, "party_id": party_id})

        result = {
            "agent": self.name,
            "order_id": order_id,
            "primary_issue": primary_issue,
            "root_cause_code": root_cause,
            "ranked_causes": [{"cause_code": root_cause, "rank": 1}],
            "responsible_parties": responsible_parties,
            "recommended_refund_brl": round(refund, 2),
            "action": action,
            "case_status": case_status,
            "confidence": confidence,
            "item_total_brl": payment_facts.get("item_total_brl", 0.0),
            "freight_total_brl": payment_facts.get("freight_total_brl", 0.0),
            "payment_total_brl": payment_facts.get("total_payment_brl", 0.0),
            "llm_policy_reasoning": llm_result.get("reasoning", "deterministic fallback"),
        }

        logger.info(
            f"[{self.name}] Decision: {primary_issue} -> {action} | "
            f"refund={refund} BRL | confidence={confidence}"
        )
        return result

    def _deterministic_fallback(self, ctx: dict) -> tuple[str, float]:
        status = ctx.get("order_status")
        total = ctx.get("total_payment_brl", 0.0)
        split = ctx.get("is_split_payment", False)
        rec = ctx.get("payment_reconciled", True)
        late = ctx.get("delivered_late")
        s_late = ctx.get("seller_handoff_late", False)

        if status == "canceled" and total > 0: return "canceled_order_paid", 0.95
        if status == "unavailable" and total > 0: return "unavailable_order_paid", 0.95
        if late and s_late: return "late_delivery_seller", 0.90
        if late and not s_late: return "late_delivery_logistics", 0.85
        if split and rec: return "valid_split_payment", 0.80
        return "unsupported_late_claim", 0.70

    def _fallback(self, order_id: str) -> dict:
        return {
            "agent": self.name,
            "order_id": order_id,
            "primary_issue": "unsupported_late_claim",
            "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
            "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
            "responsible_parties": [],
            "recommended_refund_brl": 0.0,
            "action": "reject_late_refund",
            "case_status": "no_action",
            "confidence": 0.50,
            "llm_policy_reasoning": "No data found."
        }
