"""
Verifier Agent
Responsibility: Validate evidence IDs, amounts, and output schema
before writing the final JSON file. Acts as a quality gate.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# Valid evidence ID patterns
EVIDENCE_PATTERNS = [
    re.compile(r"^order:[a-f0-9]+$"),
    re.compile(r"^item:[a-f0-9]+:\d+$"),
    re.compile(r"^payment:[a-f0-9]+:\d+$"),
    re.compile(r"^seller:[a-f0-9]+$"),
    re.compile(r"^policy:[A-Z_]+$"),
]

VALID_ROOT_CAUSES = {
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}

VALID_PRIMARY_ISSUES = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}

VALID_ACTIONS = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
}

VALID_CASE_STATUSES = {"action_required", "no_action"}


def _is_valid_evidence_id(eid: str) -> bool:
    return any(p.match(eid) for p in EVIDENCE_PATTERNS)


class VerifierAgent:
    """
    Validates the assembled output dict and writes it to output/EC_XXX.json.
    Reports validation warnings without blocking output.
    """

    name = "VerifierAgent"

    def run(self, case_id: str, output: dict) -> tuple[dict, list[str]]:
        """
        Validate and write output.
        Returns (validated_output, list_of_warnings).
        """
        warnings = []
        out = dict(output)  # shallow copy

        # --- Validate primary_issue ---
        pi = out.get("assessment", {}).get("primary_issue", "")
        if pi not in VALID_PRIMARY_ISSUES:
            warnings.append(f"Invalid primary_issue: {pi}")

        # --- Validate case_status ---
        cs = out.get("assessment", {}).get("case_status", "")
        if cs not in VALID_CASE_STATUSES:
            warnings.append(f"Invalid case_status: {cs}")

        # --- Validate confidence ---
        conf = out.get("assessment", {}).get("confidence", 0)
        if not (0.0 <= conf <= 1.0):
            warnings.append(f"confidence out of range: {conf}")
            out["assessment"]["confidence"] = max(0.0, min(1.0, conf))

        # --- Validate evidence IDs ---
        evidence_ids = out.get("evidence_ids", [])
        valid_eids = []
        for eid in evidence_ids:
            if _is_valid_evidence_id(eid):
                valid_eids.append(eid)
            else:
                warnings.append(f"Invalid evidence ID removed: {eid}")
        out["evidence_ids"] = valid_eids[:10]  # max 10

        # --- Validate root causes ---
        rca = out.get("root_cause_analysis", {})
        ranked = rca.get("ranked_causes", [])
        valid_causes = [
            c for c in ranked
            if c.get("cause_code") in VALID_ROOT_CAUSES
        ]
        if len(valid_causes) != len(ranked):
            warnings.append("Some ranked_causes had invalid cause_code values")
        out["root_cause_analysis"]["ranked_causes"] = valid_causes[:3]  # max 3

        # --- Validate financial resolution ---
        fin = out.get("financial_resolution", {})
        refund = fin.get("recommended_refund_brl", 0.0)
        if not isinstance(refund, (int, float)):
            warnings.append(f"Invalid recommended_refund_brl: {refund}")
            out["financial_resolution"]["recommended_refund_brl"] = 0.0

        # --- Enforce max entity limits ---
        ae = out.get("affected_entities", {})
        out["affected_entities"] = {
            "order_ids":   ae.get("order_ids", [])[:5],
            "item_ids":    ae.get("item_ids", [])[:5],
            "seller_ids":  ae.get("seller_ids", [])[:5],
            "payment_ids": ae.get("payment_ids", [])[:5],
        }

        # --- Validate actions ---
        actions = out.get("resolution_actions", [])
        valid_actions = [a for a in actions if a in VALID_ACTIONS]
        if len(valid_actions) != len(actions):
            warnings.append("Some resolution_actions were invalid")
        out["resolution_actions"] = valid_actions[:5]  # max 5

        # --- Write to file ---
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{case_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

        if warnings:
            logger.warning(f"[{self.name}] {case_id} - {len(warnings)} warnings: {warnings}")
        else:
            logger.info(f"[{self.name}] {case_id} - validated and written to {out_path}")

        return out, warnings
