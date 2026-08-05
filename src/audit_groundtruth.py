"""Build an independent local oracle from README's EC_POLICY_V1 rules.

This module intentionally does not import dispute_pipeline.  It is an audit
tool, not part of the submission path, and writes only under audit/.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CENT = Decimal("0.01")

POLICIES = {
    "canceled_order_paid": ("ORDER_CANCELED_AFTER_PAYMENT", "action_required", "issue_full_refund"),
    "unavailable_order_paid": ("ORDER_UNAVAILABLE_AFTER_PAYMENT", "action_required", "issue_full_refund"),
    "late_delivery_seller": ("SELLER_HANDOFF_AFTER_LIMIT", "action_required", "refund_freight"),
    "late_delivery_logistics": ("CARRIER_DELIVERED_AFTER_ESTIMATE", "action_required", "refund_freight"),
    "valid_split_payment": ("MULTIPLE_PAYMENTS_RECONCILED", "no_action", "explain_valid_split_payment"),
    "unsupported_late_claim": ("DELIVERY_WITHIN_ESTIMATE", "no_action", "reject_late_refund"),
}


def read_rows(name: str) -> list[dict[str, str]]:
    with (ROOT / "data" / name).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_time(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def after(left: str, right: str) -> bool:
    left_time, right_time = parse_time(left), parse_time(right)
    return bool(left_time and right_time and left_time > right_time)


def amount(value: str) -> Decimal:
    return Decimal(value or "0")


def money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def add_evidence(evidence: list[str], entries: list[str]) -> None:
    for entry in entries:
        if entry not in evidence and len(evidence) < 9:
            evidence.append(entry)


def build_oracle(
    case: dict[str, Any],
    order: dict[str, str],
    items: list[dict[str, str]],
    payments: list[dict[str, str]],
) -> dict[str, Any]:
    order_id = order["order_id"]
    item_total = sum((amount(row["price"]) for row in items), Decimal("0"))
    freight_total = sum((amount(row["freight_value"]) for row in items), Decimal("0"))
    payment_total = sum((amount(row["payment_value"]) for row in payments), Decimal("0"))
    reconciled = abs(payment_total - item_total - freight_total) <= Decimal("0.10")
    delivered_late = after(order["order_delivered_customer_date"], order["order_estimated_delivery_date"])
    late_sellers = sorted({
        row["seller_id"]
        for row in items
        if after(order["order_delivered_carrier_date"], row["shipping_limit_date"])
    })

    status = order["order_status"]
    if status == "canceled" and payment_total > 0:
        issue = "canceled_order_paid"
    elif status == "unavailable" and payment_total > 0:
        issue = "unavailable_order_paid"
    elif delivered_late and late_sellers:
        issue = "late_delivery_seller"
    elif delivered_late:
        issue = "late_delivery_logistics"
    elif len(payments) >= 2 and reconciled:
        issue = "valid_split_payment"
    elif reconciled:
        issue = "unsupported_late_claim"
    else:
        raise ValueError(f"No EC_POLICY_V1 outcome for {case['case_id']}")

    cause, case_status, action = POLICIES[issue]
    ordered_items = sorted(
        items,
        key=lambda row: (row["seller_id"] not in late_sellers, int(row["order_item_id"])),
    )
    visible_items = ordered_items[:5]
    visible_payments = sorted(payments, key=lambda row: int(row["payment_sequential"]))[:5]
    item_ids = [f"{order_id}:{row['order_item_id']}" for row in visible_items]
    payment_ids = [f"{order_id}:{row['payment_sequential']}" for row in visible_payments]
    visible_sellers = sorted({row["seller_id"] for row in visible_items})
    seller_ids = (late_sellers + [value for value in visible_sellers if value not in late_sellers])[:5]

    refund = Decimal("0")
    responsible: list[dict[str, str]] = []
    if issue in {"canceled_order_paid", "unavailable_order_paid"}:
        refund = payment_total
        responsible = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
    elif issue == "late_delivery_seller":
        refund = freight_total
        responsible = [{"party_type": "seller", "party_id": value} for value in late_sellers[:3]]
    elif issue == "late_delivery_logistics":
        refund = freight_total
        responsible = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]

    evidence = [f"order:{order_id}"]
    if issue in {"canceled_order_paid", "unavailable_order_paid"}:
        add_evidence(evidence, [f"payment:{value}" for value in payment_ids])
    elif issue == "late_delivery_seller":
        add_evidence(evidence, [f"item:{value}" for value in item_ids[:3]])
        add_evidence(evidence, [f"seller:{value}" for value in seller_ids[:2]])
        add_evidence(evidence, [f"payment:{value}" for value in payment_ids[:3]])
    elif issue == "late_delivery_logistics":
        add_evidence(evidence, [f"item:{value}" for value in item_ids[:3]])
        add_evidence(evidence, [f"payment:{value}" for value in payment_ids[:3]])
    elif issue == "valid_split_payment":
        add_evidence(evidence, [f"payment:{value}" for value in payment_ids])
        add_evidence(evidence, [f"item:{value}" for value in item_ids[:3]])
    else:
        add_evidence(evidence, [f"item:{value}" for value in item_ids[:3]])
        add_evidence(evidence, [f"payment:{value}" for value in payment_ids[:3]])
    evidence.append(f"policy:{cause}")

    return {
        "case_id": case["case_id"],
        "assessment": {"primary_issue": issue, "case_status": case_status, "confidence": 1.0},
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "payment_ids": payment_ids,
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": cause, "rank": 1}],
            "responsible_parties": responsible,
        },
        "evidence_ids": evidence,
        "financial_resolution": {
            "currency": "BRL",
            "item_total_brl": money(item_total),
            "freight_total_brl": money(freight_total),
            "payment_total_brl": money(payment_total),
            "recommended_refund_brl": money(refund),
        },
        "resolution_actions": [action],
    }


def differences(expected: Any, actual: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                result.append({"path": child, "expected": expected.get(key), "actual": actual.get(key)})
            else:
                result.extend(differences(expected[key], actual[key], child))
        return result
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def main() -> None:
    orders = {row["order_id"]: row for row in read_rows("olist_orders_dataset.csv")}
    items_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_rows("olist_order_items_dataset.csv"):
        items_by_order[row["order_id"]].append(row)
    payments_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_rows("olist_order_payments_dataset.csv"):
        payments_by_order[row["order_id"]].append(row)

    oracle: dict[str, dict[str, Any]] = {}
    all_differences: list[dict[str, Any]] = []
    for input_path in sorted((ROOT / "input").glob("EC_*.json")):
        case = json.loads(input_path.read_text(encoding="utf-8"))
        order_id = case["customer_request"]["claimed_order_id"]
        expected = build_oracle(case, orders[order_id], items_by_order[order_id], payments_by_order[order_id])
        actual = json.loads((ROOT / "output" / input_path.name).read_text(encoding="utf-8"))
        oracle[case["case_id"]] = expected
        for mismatch in differences(expected, actual):
            all_differences.append({"case_id": case["case_id"], **mismatch})

    audit_dir = ROOT / "audit"
    audit_dir.mkdir(exist_ok=True)
    (audit_dir / "local_groundtruth.json").write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "oracle": "Independent implementation of README EC_POLICY_V1; not the hidden grader ground truth",
        "case_count": len(oracle),
        "difference_count": len(all_differences),
        "differences": all_differences,
    }
    (audit_dir / "groundtruth_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Local ground truth cases: {len(oracle)}")
    print(f"Pipeline field differences: {len(all_differences)}")


if __name__ == "__main__":
    main()
