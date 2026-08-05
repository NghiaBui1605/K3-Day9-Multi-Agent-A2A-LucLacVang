"""
Order & Seller Agent – LLM-powered
Uses LLM to analyze order facts and reason about seller responsibility.
LLM role: interpret raw data, flag anomalies, summarize seller handoff status.
"""

import json
import logging
from agents.data_loader import get_order, get_order_items, get_seller, get_customer, ts
from agents.llm_client import call_llm_json

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an Order & Seller Analysis Agent for an e-commerce dispute resolution system.
Your job is to analyze raw order data and extract structured facts.
You must respond ONLY with valid JSON. No explanations, no markdown outside the JSON block.
Always base your analysis on the actual data provided - never invent facts."""


class OrderSellerAgent:
    name = "OrderSellerAgent"

    def run(self, case: dict) -> dict:
        order_id = case["customer_request"]["claimed_order_id"]
        logger.info(f"[{self.name}] Processing order: {order_id}")

        order = get_order(order_id)
        if order is None:
            logger.warning(f"[{self.name}] Order not found: {order_id}")
            return {"agent": self.name, "order_id": order_id, "found": False, "error": "order_not_found"}

        items = get_order_items(order_id)
        seller_ids = list({item["seller_id"] for item in items if item.get("seller_id")})
        sellers_info = {sid: get_seller(sid) for sid in seller_ids}

        items_summary = [
            {
                "order_item_id": item.get("order_item_id"),
                "seller_id": item.get("seller_id"),
                "price": item.get("price", 0.0),
                "freight_value": item.get("freight_value", 0.0),
                "shipping_limit_date": ts(item.get("shipping_limit_date")),
            }
            for item in items
        ]

        # Raw data context for LLM
        raw_data = {
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "order_purchase_timestamp": ts(order.get("order_purchase_timestamp")),
            "order_approved_at": ts(order.get("order_approved_at")),
            "order_delivered_carrier_date": ts(order.get("order_delivered_carrier_date")),
            "order_delivered_customer_date": ts(order.get("order_delivered_customer_date")),
            "order_estimated_delivery_date": ts(order.get("order_estimated_delivery_date")),
            "items": items_summary,
            "seller_ids": seller_ids,
        }

        user_prompt = f"""Analyze this order data and return a JSON object with exactly these fields:
- "order_status": string (from data)
- "item_count": integer
- "seller_ids": list of seller ID strings
- "any_anomaly": boolean (true if status is canceled/unavailable, or any field is missing)
- "anomaly_description": string (brief description or "none")
- "delivered_carrier_date": string or null
- "delivered_customer_date": string or null
- "estimated_delivery_date": string or null

Order data:
{json.dumps(raw_data, indent=2)}

Return ONLY a JSON object, no other text."""

        llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt, max_tokens=400)

        # Merge LLM analysis with raw facts (data takes precedence for IDs/timestamps)
        result = {
            "agent": self.name,
            "order_id": order_id,
            "found": True,
            "order_status": order.get("order_status"),
            "customer_id": order.get("customer_id"),
            "purchase_timestamp": ts(order.get("order_purchase_timestamp")),
            "approved_at": ts(order.get("order_approved_at")),
            "delivered_carrier_date": ts(order.get("order_delivered_carrier_date")),
            "delivered_customer_date": ts(order.get("order_delivered_customer_date")),
            "estimated_delivery_date": ts(order.get("order_estimated_delivery_date")),
            "items": items_summary,
            "seller_ids": seller_ids,
            "sellers_info": sellers_info,
            "item_count": len(items),
            # LLM-generated analysis
            "llm_anomaly_detected": llm_result.get("any_anomaly", False),
            "llm_anomaly_description": llm_result.get("anomaly_description", "none"),
        }

        logger.info(
            f"[{self.name}] Done - status={result['order_status']}, "
            f"items={result['item_count']}, llm_anomaly={result['llm_anomaly_detected']}"
        )
        return result
