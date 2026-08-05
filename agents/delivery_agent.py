"""
Delivery Agent – LLM-powered
Uses LLM to reason about delivery timing and attribute responsibility.
LLM role: analyze timestamps, determine who is responsible for the delay.
"""

import json
import logging
from datetime import datetime
from typing import Optional
from agents.llm_client import call_llm_json

logger = logging.getLogger(__name__)

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
]

SYSTEM_PROMPT = """You are a Delivery Analysis Agent for an e-commerce dispute resolution system.
Your job is to analyze delivery timestamps and determine if delivery was late and who is responsible.
Key rules:
- If delivered_customer_date > estimated_delivery_date: delivery was LATE
- If delivered_carrier_date > shipping_limit_date of any item: the SELLER handed off late
- If delivery was late but seller handed off on time: LOGISTICS PROVIDER is responsible
You must respond ONLY with valid JSON. Base all conclusions strictly on the timestamps provided."""


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val or val in ("nan", "None", "NaT"):
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


class DeliveryAgent:
    name = "DeliveryAgent"

    def run(self, order_facts: dict) -> dict:
        order_id = order_facts["order_id"]
        logger.info(f"[{self.name}] Processing delivery timing for: {order_id}")

        if not order_facts.get("found"):
            return {"agent": self.name, "order_id": order_id, "found": False, "error": "order_not_found"}

        # Deterministic timestamp comparison
        delivered_carrier = _parse_dt(order_facts.get("delivered_carrier_date"))
        delivered_customer = _parse_dt(order_facts.get("delivered_customer_date"))
        estimated_delivery = _parse_dt(order_facts.get("estimated_delivery_date"))

        delivered_late: Optional[bool] = None
        days_late: Optional[float] = None
        if delivered_customer and estimated_delivery:
            delivered_late = delivered_customer > estimated_delivery
            delta = delivered_customer - estimated_delivery
            days_late = round(delta.total_seconds() / 86400, 2)

        items = order_facts.get("items", [])
        late_seller_ids = []
        seller_handoff_details = []

        for item in items:
            limit_dt = _parse_dt(item.get("shipping_limit_date"))
            sid = item.get("seller_id")
            handoff_late = None
            if delivered_carrier and limit_dt:
                handoff_late = delivered_carrier > limit_dt
            seller_handoff_details.append({
                "order_item_id": item.get("order_item_id"),
                "seller_id": sid,
                "shipping_limit_date": item.get("shipping_limit_date"),
                "delivered_carrier_date": order_facts.get("delivered_carrier_date"),
                "seller_handoff_late": handoff_late,
            })
            if handoff_late and sid and sid not in late_seller_ids:
                late_seller_ids.append(sid)

        seller_handoff_late = len(late_seller_ids) > 0

        # Build timestamp context for LLM
        timing_context = {
            "delivered_carrier_date": order_facts.get("delivered_carrier_date"),
            "delivered_customer_date": order_facts.get("delivered_customer_date"),
            "estimated_delivery_date": order_facts.get("estimated_delivery_date"),
            "delivery_was_late": delivered_late,
            "days_late": days_late,
            "seller_handoff_details": seller_handoff_details,
            "late_seller_ids": late_seller_ids,
            "seller_handed_off_late": seller_handoff_late,
        }

        user_prompt = f"""Analyze these delivery timestamps and return a JSON object with exactly these fields:
- "delivery_verdict": string (one of: "on_time", "late_seller_fault", "late_logistics_fault", "not_delivered", "unknown")
- "responsible_party": string (one of: "seller", "logistics_provider", "none", "unknown")
- "confidence": float between 0.0 and 1.0
- "reasoning": string (2-3 sentences explaining what the timestamps show and who is responsible)

Delivery data:
{json.dumps(timing_context, indent=2)}

Return ONLY a JSON object."""

        llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt, max_tokens=350)

        result = {
            "agent": self.name,
            "order_id": order_id,
            "found": True,
            "delivered_carrier_date": order_facts.get("delivered_carrier_date"),
            "delivered_customer_date": order_facts.get("delivered_customer_date"),
            "estimated_delivery_date": order_facts.get("estimated_delivery_date"),
            "delivered_late": delivered_late,
            "days_late": days_late,
            "seller_handoff_late": seller_handoff_late,
            "late_seller_ids": late_seller_ids,
            "seller_handoff_details": seller_handoff_details,
            # LLM-generated analysis
            "llm_delivery_verdict": llm_result.get("delivery_verdict", "unknown"),
            "llm_responsible_party": llm_result.get("responsible_party", "unknown"),
            "llm_confidence": llm_result.get("confidence", 0.5),
            "llm_reasoning": llm_result.get("reasoning", ""),
        }

        logger.info(
            f"[{self.name}] Done - late={delivered_late}, seller_fault={seller_handoff_late}, "
            f"llm_verdict={result['llm_delivery_verdict']}"
        )
        return result
