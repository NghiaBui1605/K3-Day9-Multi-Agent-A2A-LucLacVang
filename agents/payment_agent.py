"""
Payment Agent – LLM-powered
Uses LLM to reconcile payments and reason about payment anomalies.
LLM role: assess if payment matches expected total, detect issues.
"""

import json
import logging
from agents.data_loader import get_order_payments
from agents.llm_client import call_llm_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Payment Reconciliation Agent for an e-commerce dispute system.
Your job is to analyze payment data and determine if payments are correct.
You must respond ONLY with valid JSON. Base analysis strictly on the numbers provided."""


class PaymentAgent:
    name = "PaymentAgent"

    def run(self, order_facts: dict) -> dict:
        order_id = order_facts["order_id"]
        logger.info(f"[{self.name}] Processing payments for: {order_id}")

        if not order_facts.get("found"):
            return {"agent": self.name, "order_id": order_id, "found": False, "error": "order_not_found"}

        payments = get_order_payments(order_id)

        payment_rows = []
        total_payment = 0.0
        payment_types = set()

        for p in payments:
            pval = float(p.get("payment_value", 0.0) or 0.0)
            total_payment += pval
            payment_types.add(p.get("payment_type", "unknown"))
            payment_rows.append({
                "payment_sequential": p.get("payment_sequential"),
                "payment_type": p.get("payment_type"),
                "payment_installments": p.get("payment_installments"),
                "payment_value": round(pval, 2),
            })

        total_payment = round(total_payment, 2)
        items = order_facts.get("items", [])
        item_total = round(sum(float(i.get("price", 0.0) or 0.0) for i in items), 2)
        freight_total = round(sum(float(i.get("freight_value", 0.0) or 0.0) for i in items), 2)
        expected_total = round(item_total + freight_total, 2)
        payment_diff = round(abs(total_payment - expected_total), 2)
        payment_reconciled = payment_diff <= 0.10

        # LLM reconciliation reasoning
        payment_context = {
            "payment_rows": payment_rows,
            "total_payment_brl": total_payment,
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected_total,
            "difference_brl": payment_diff,
            "tolerance_brl": 0.10,
        }

        user_prompt = f"""Analyze this payment data and return a JSON object with exactly these fields:
- "is_split_payment": boolean (true if 2 or more payment rows)
- "payment_matches": boolean (true if difference <= 0.10 BRL)
- "payment_assessment": string (one of: "correct", "overpaid", "underpaid", "split_payment_valid", "no_payment")
- "reasoning": string (1-2 sentences explaining your assessment based on the numbers)

Payment data:
{json.dumps(payment_context, indent=2)}

Return ONLY a JSON object."""

        llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt, max_tokens=300)

        result = {
            "agent": self.name,
            "order_id": order_id,
            "found": True,
            "payment_rows": payment_rows,
            "payment_count": len(payment_rows),
            "total_payment_brl": total_payment,
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected_total,
            "payment_diff_brl": payment_diff,
            "payment_reconciled": payment_reconciled,
            "is_split_payment": len(payment_rows) >= 2,
            "payment_types": list(payment_types),
            # LLM assessment
            "llm_payment_assessment": llm_result.get("payment_assessment", "unknown"),
            "llm_payment_reasoning": llm_result.get("reasoning", ""),
        }

        logger.info(
            f"[{self.name}] Done - total={total_payment} BRL, "
            f"split={result['is_split_payment']}, llm={result['llm_payment_assessment']}"
        )
        return result
