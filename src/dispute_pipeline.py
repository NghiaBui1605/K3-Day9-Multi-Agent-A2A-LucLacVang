"""Deterministic multi-agent-style pipeline for EC_POLICY_V1.

The agents are represented by small, independently testable functions.  They
only hand over facts derived from the local Olist CSV files; no agent invents
events that are absent from the dataset.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from config import DEFAULT_OPENROUTER_MODEL, MODEL_PARAMETER_SIZE


POLICY_VERSION = "EC_POLICY_V1"
POLICY_ISSUES = {
    "canceled_order_paid": ("ORDER_CANCELED_AFTER_PAYMENT", "action_required", "issue_full_refund"),
    "unavailable_order_paid": ("ORDER_UNAVAILABLE_AFTER_PAYMENT", "action_required", "issue_full_refund"),
    "late_delivery_seller": ("SELLER_HANDOFF_AFTER_LIMIT", "action_required", "refund_freight"),
    "late_delivery_logistics": ("CARRIER_DELIVERED_AFTER_ESTIMATE", "action_required", "refund_freight"),
    "valid_split_payment": ("MULTIPLE_PAYMENTS_RECONCILED", "no_action", "explain_valid_split_payment"),
    "unsupported_late_claim": ("DELIVERY_WITHIN_ESTIMATE", "no_action", "reject_late_refund"),
}
POLICY_ORDER = tuple(POLICY_ISSUES)
CENT = Decimal("0.01")
OPENROUTER_CACHE_VERSION = "qwen3-json-v2-policy-evidence"


def money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def decimal(value: str) -> Decimal:
    return Decimal(value or "0")


def parse_time(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def is_after(left: str, right: str) -> bool:
    """Compare the timestamp strings as timestamps in the source CSV."""
    left_time, right_time = parse_time(left), parse_time(right)
    return bool(left_time and right_time and left_time > right_time)


@dataclass(frozen=True)
class Dataset:
    orders: dict[str, dict[str, str]]
    items: dict[str, list[dict[str, str]]]
    payments: dict[str, list[dict[str, str]]]

    @classmethod
    def load(cls, data_dir: Path) -> "Dataset":
        def rows(name: str) -> Iterable[dict[str, str]]:
            with (data_dir / name).open("r", encoding="utf-8", newline="") as handle:
                yield from csv.DictReader(handle)

        orders = {row["order_id"]: row for row in rows("olist_orders_dataset.csv")}
        items: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows("olist_order_items_dataset.csv"):
            items[row["order_id"]].append(row)
        payments: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows("olist_order_payments_dataset.csv"):
            payments[row["order_id"]].append(row)
        return cls(orders, dict(items), dict(payments))


@dataclass(frozen=True)
class CaseFacts:
    order: dict[str, str]
    items: list[dict[str, str]]
    payments: list[dict[str, str]]
    item_total: Decimal
    freight_total: Decimal
    payment_total: Decimal
    delivered_late: bool
    late_seller_ids: list[str]
    reconciled: bool


def order_and_seller_agent(dataset: Dataset, order_id: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Fetch the order and item/seller facts; this is the only order lookup."""
    try:
        return dataset.orders[order_id], dataset.items.get(order_id, [])
    except KeyError as error:
        raise ValueError(f"claimed_order_id does not exist in orders CSV: {order_id}") from error


def payment_agent(dataset: Dataset, order_id: str, items: list[dict[str, str]]) -> tuple[list[dict[str, str]], Decimal, Decimal, Decimal]:
    """Reconcile payment rows with item price plus freight."""
    payments = dataset.payments.get(order_id, [])
    item_total = sum((decimal(item["price"]) for item in items), Decimal("0"))
    freight_total = sum((decimal(item["freight_value"]) for item in items), Decimal("0"))
    payment_total = sum((decimal(payment["payment_value"]) for payment in payments), Decimal("0"))
    return payments, item_total, freight_total, payment_total


def delivery_agent(order: dict[str, str], items: list[dict[str, str]]) -> tuple[bool, list[str]]:
    """Determine whether delivery was late and which sellers missed handoff limits."""
    delivered_late = is_after(
        order["order_delivered_customer_date"], order["order_estimated_delivery_date"]
    )
    late_sellers = sorted(
        {
            item["seller_id"]
            for item in items
            if is_after(order["order_delivered_carrier_date"], item["shipping_limit_date"])
        }
    )
    return delivered_late, late_sellers


def collect_facts(dataset: Dataset, order_id: str) -> CaseFacts:
    order, items = order_and_seller_agent(dataset, order_id)
    payments, item_total, freight_total, payment_total = payment_agent(dataset, order_id, items)
    delivered_late, late_seller_ids = delivery_agent(order, items)
    reconciled = abs(payment_total - item_total - freight_total) <= Decimal("0.10")
    return CaseFacts(
        order=order,
        items=items,
        payments=payments,
        item_total=item_total,
        freight_total=freight_total,
        payment_total=payment_total,
        delivered_late=delivered_late,
        late_seller_ids=late_seller_ids,
        reconciled=reconciled,
    )


def policy_agent(facts: CaseFacts) -> str:
    """Apply EC_POLICY_V1 in its documented priority order."""
    status = facts.order["order_status"]
    if status == "canceled" and facts.payment_total > 0:
        return "canceled_order_paid"
    if status == "unavailable" and facts.payment_total > 0:
        return "unavailable_order_paid"
    if facts.delivered_late and facts.late_seller_ids:
        return "late_delivery_seller"
    if facts.delivered_late and not facts.late_seller_ids:
        return "late_delivery_logistics"
    if len(facts.payments) >= 2 and facts.reconciled:
        return "valid_split_payment"
    if not facts.delivered_late and facts.reconciled:
        return "unsupported_late_claim"
    raise ValueError(
        f"Order {facts.order['order_id']} cannot be classified by EC_POLICY_V1 "
        "with the available data."
    )


def build_assessment(case: dict[str, Any], facts: CaseFacts, issue: str) -> dict[str, Any]:
    cause_code, case_status, action = POLICY_ISSUES[issue]
    order_id = facts.order["order_id"]
    # For seller-delay cases, retain the violating seller's item before any
    # truncation so the affected entities and evidence support the decision.
    prioritized_items = sorted(
        facts.items,
        key=lambda item: (item["seller_id"] not in facts.late_seller_ids, int(item["order_item_id"])),
    )
    visible_items = prioritized_items[:5]
    # CSV row order is not part of the output contract.  Canonicalize payment
    # IDs by their numeric sequence so entity/evidence lists are reproducible
    # and match the natural payment:order_id:1, :2, ... ordering.
    visible_payments = sorted(
        facts.payments, key=lambda payment: int(payment["payment_sequential"])
    )[:5]
    visible_seller_ids = sorted({item["seller_id"] for item in visible_items})
    seller_ids = (facts.late_seller_ids + [
        seller_id for seller_id in visible_seller_ids if seller_id not in facts.late_seller_ids
    ])[:5]
    item_ids = [f"{order_id}:{item['order_item_id']}" for item in visible_items]
    payment_ids = [f"{order_id}:{payment['payment_sequential']}" for payment in visible_payments]

    responsible: list[dict[str, str]] = []
    refund = Decimal("0")
    if issue in {"canceled_order_paid", "unavailable_order_paid"}:
        responsible = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund = facts.payment_total
    elif issue == "late_delivery_seller":
        responsible = [
            {"party_type": "seller", "party_id": seller_id}
            for seller_id in facts.late_seller_ids[:3]
        ]
        refund = facts.freight_total
    elif issue == "late_delivery_logistics":
        responsible = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]
        refund = facts.freight_total

    # Evidence is not the same as every entity related to an order. Select
    # only rows that prove the active policy predicate or its financial
    # resolution. For example, a seller master row contains location data and
    # is useful only when that seller is the responsible party.
    evidence = [f"order:{order_id}"]
    if issue in {"canceled_order_paid", "unavailable_order_paid"}:
        supporting_ids = [f"payment:{payment_id}" for payment_id in payment_ids]
    elif issue == "late_delivery_seller":
        violating_item_ids = [
            f"{order_id}:{item['order_item_id']}"
            for item in prioritized_items
            if item["seller_id"] in facts.late_seller_ids
            and is_after(
                facts.order["order_delivered_carrier_date"], item["shipping_limit_date"]
            )
        ]
        supporting_ids = [f"item:{item_id}" for item_id in violating_item_ids]
        supporting_ids.extend(f"payment:{payment_id}" for payment_id in payment_ids)
        supporting_ids.extend(f"seller:{seller_id}" for seller_id in facts.late_seller_ids)
    elif issue == "valid_split_payment":
        supporting_ids = [f"payment:{payment_id}" for payment_id in payment_ids]
        supporting_ids.extend(f"item:{item_id}" for item_id in item_ids)
    else:
        supporting_ids = [f"item:{item_id}" for item_id in item_ids]
        supporting_ids.extend(f"payment:{payment_id}" for payment_id in payment_ids)
    evidence.extend(supporting_ids[:8])
    evidence.append(f"policy:{cause_code}")

    return {
        "case_id": case["case_id"],
        "assessment": {
            "primary_issue": issue,
            "case_status": case_status,
            # Every supported outcome is selected by complete, source-backed
            # policy predicates and then independently verified below.
            "confidence": 1.0,
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "payment_ids": payment_ids,
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": cause_code, "rank": 1}],
            "responsible_parties": responsible,
        },
        "evidence_ids": evidence[:10],
        "financial_resolution": {
            "currency": "BRL",
            "item_total_brl": money(facts.item_total),
            "freight_total_brl": money(facts.freight_total),
            "payment_total_brl": money(facts.payment_total),
            "recommended_refund_brl": money(refund),
        },
        "resolution_actions": [action],
    }


def verifier_agent(result: dict[str, Any], facts: CaseFacts) -> None:
    """Validate schema limits, source-backed IDs, money and policy decisions."""
    assessment = result["assessment"]
    if assessment["primary_issue"] not in POLICY_ISSUES:
        raise ValueError("Unknown primary issue")
    if assessment["case_status"] not in {"action_required", "no_action"}:
        raise ValueError("Invalid case_status")
    if not 0 <= assessment["confidence"] <= 1:
        raise ValueError("confidence must be in [0, 1]")
    if len(result["evidence_ids"]) > 10:
        raise ValueError("Too many evidence IDs")
    if len(result["root_cause_analysis"]["ranked_causes"]) > 3:
        raise ValueError("Too many root causes")
    if len(result["root_cause_analysis"]["responsible_parties"]) > 3:
        raise ValueError("Too many responsible parties")
    if len(result["resolution_actions"]) > 5:
        raise ValueError("Too many actions")
    for field in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
        if len(result["affected_entities"][field]) > 5:
            raise ValueError(f"Too many {field}")
    allowed_prefixes = ("order:", "item:", "payment:", "seller:", "policy:")
    if any(not evidence.startswith(allowed_prefixes) for evidence in result["evidence_ids"]):
        raise ValueError("Invalid evidence ID prefix")

    order_id = facts.order["order_id"]
    valid_entities = {
        "order_ids": {order_id},
        "item_ids": {f"{order_id}:{item['order_item_id']}" for item in facts.items},
        "seller_ids": {item["seller_id"] for item in facts.items},
        "payment_ids": {
            f"{order_id}:{payment['payment_sequential']}" for payment in facts.payments
        },
    }
    for field, valid_ids in valid_entities.items():
        submitted = result["affected_entities"][field]
        if len(submitted) != len(set(submitted)):
            raise ValueError(f"Duplicate {field}")
        if not set(submitted).issubset(valid_ids):
            raise ValueError(f"Unknown source ID in {field}")
    if result["affected_entities"]["order_ids"] != [order_id]:
        raise ValueError("Assessment must contain its claimed order ID")

    cause_code, expected_status, expected_action = POLICY_ISSUES[assessment["primary_issue"]]
    if assessment["case_status"] != expected_status:
        raise ValueError("case_status does not match the selected policy")
    if result["root_cause_analysis"]["ranked_causes"] != [
        {"cause_code": cause_code, "rank": 1}
    ]:
        raise ValueError("Root cause does not match the selected policy")
    if result["resolution_actions"] != [expected_action]:
        raise ValueError("Resolution action does not match the selected policy")

    valid_evidence = {f"order:{order_id}", f"policy:{cause_code}"}
    valid_evidence.update(f"item:{entity_id}" for entity_id in valid_entities["item_ids"])
    valid_evidence.update(f"seller:{entity_id}" for entity_id in valid_entities["seller_ids"])
    valid_evidence.update(f"payment:{entity_id}" for entity_id in valid_entities["payment_ids"])
    submitted_evidence = result["evidence_ids"]
    if len(submitted_evidence) != len(set(submitted_evidence)):
        raise ValueError("Duplicate evidence ID")
    if not set(submitted_evidence).issubset(valid_evidence):
        raise ValueError("Evidence ID is not backed by a source row or policy")
    if f"order:{order_id}" not in submitted_evidence or f"policy:{cause_code}" not in submitted_evidence:
        raise ValueError("Order and policy evidence are required")
    if assessment["primary_issue"] != "late_delivery_seller" and any(
        evidence.startswith("seller:") for evidence in submitted_evidence
    ):
        raise ValueError("Seller evidence is only relevant to seller-responsible cases")
    if assessment["primary_issue"] in {"canceled_order_paid", "unavailable_order_paid"} and any(
        evidence.startswith("item:") for evidence in submitted_evidence
    ):
        raise ValueError("Item evidence does not prove cancellation or availability after payment")

    financial = result["financial_resolution"]
    expected_totals = {
        "item_total_brl": money(facts.item_total),
        "freight_total_brl": money(facts.freight_total),
        "payment_total_brl": money(facts.payment_total),
    }
    for field, expected in expected_totals.items():
        if Decimal(str(financial[field])) != Decimal(str(expected)):
            raise ValueError(f"Incorrect {field}")
    expected_refund = (
        facts.payment_total
        if assessment["primary_issue"] in {"canceled_order_paid", "unavailable_order_paid"}
        else facts.freight_total
        if assessment["primary_issue"] in {"late_delivery_seller", "late_delivery_logistics"}
        else Decimal("0")
    )
    if Decimal(str(financial["recommended_refund_brl"])) != Decimal(str(money(expected_refund))):
        raise ValueError("Incorrect recommended_refund_brl")


def process_case(dataset: Dataset, case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if case.get("policy_version") != POLICY_VERSION:
        raise ValueError(f"Unsupported policy version in {case.get('case_id')}")
    order_id = case.get("customer_request", {}).get("claimed_order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError(f"Missing claimed_order_id in {case.get('case_id')}")
    facts = collect_facts(dataset, order_id)
    issue = policy_agent(facts)
    result = build_assessment(case, facts, issue)
    verifier_agent(result, facts)
    trace = {
        "case_id": case["case_id"],
        "order_id": order_id,
        "handoffs": ["order_seller", "payment", "delivery", "policy", "verifier"],
        "primary_issue": issue,
        "verified": True,
    }
    return result, trace


def process_directory(
    data_dir: Path,
    input_dir: Path,
    output_dir: Path,
    logging_dir: Path,
    llm_client: Any | None = None,
    workers: int = 1,
) -> int:
    dataset = Dataset.load(data_dir)
    input_files = sorted(input_dir.glob("EC_*.json"))
    if not input_files:
        raise ValueError("No EC_*.json input files found. Run --generate-mocks for local development.")
    expected_names = [f"EC_{number:03d}.json" for number in range(1, 51)]
    actual_names = [path.name for path in input_files]
    if actual_names != expected_names:
        raise ValueError("Input must contain exactly EC_001.json through EC_050.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    logging_dir.mkdir(parents=True, exist_ok=True)
    orchestrator = None
    if llm_client is not None:
        # Delayed import avoids a module cycle: llm_multi_agent imports the
        # source-backed facts and policy helpers from this module.
        from llm_multi_agent import LLMOrchestrator

        orchestrator = LLMOrchestrator(llm_client, dataset)
        cache_dir = logging_dir / ".openrouter-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        cache_dir = None

    def process_input(input_file: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        case = json.loads(input_file.read_text(encoding="utf-8"))
        if case.get("case_id") != input_file.stem:
            raise ValueError(f"case_id does not match filename: {input_file.name}")
        result, trace = process_case(dataset, case)
        if orchestrator is not None:
            cache_file = cache_dir / input_file.name
            if cache_file.exists():
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if (
                    cached.get("cache_version") == OPENROUTER_CACHE_VERSION
                    and cached.get("model") == llm_client.model
                    and cached.get("case_id") == case["case_id"]
                    and cached.get("order_id") == case["customer_request"]["claimed_order_id"]
                ):
                    return input_file, cached["result"], cached["trace"]
            orchestration = orchestrator.run(
                case["customer_request"]["message"], case, result, []
            )
            trace["model"] = llm_client.model
            trace["llm_handoffs"] = orchestration.handoffs
            trace["coordinator_reply"] = orchestration.reply
            trace["llm_verified"] = True
            cache_payload = {
                "cache_version": OPENROUTER_CACHE_VERSION,
                "model": llm_client.model,
                "case_id": case["case_id"],
                "order_id": case["customer_request"]["claimed_order_id"],
                "result": result,
                "trace": trace,
            }
            temporary_cache_file = cache_file.with_suffix(".tmp")
            temporary_cache_file.write_text(
                json.dumps(cache_payload, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            temporary_cache_file.replace(cache_file)
        return input_file, result, trace

    effective_workers = max(1, workers) if orchestrator is not None else 1
    if effective_workers == 1:
        processed = list(map(process_input, input_files))
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            processed = list(executor.map(process_input, input_files))

    traces = []
    for input_file, result, trace in processed:
        output_file = output_dir / input_file.name
        output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        traces.append(trace)
    (logging_dir / "trace.jsonl").write_text(
        "".join(json.dumps(trace, ensure_ascii=False) + "\n" for trace in traces), encoding="utf-8"
    )
    metadata = {
        "model": {
            "chatbot": DEFAULT_OPENROUTER_MODEL,
            "policy_agents": DEFAULT_OPENROUTER_MODEL if orchestrator is not None else "none (deterministic rules)",
        },
        "parameter_size": {
            "chatbot": MODEL_PARAMETER_SIZE,
            "policy_agents": MODEL_PARAMETER_SIZE if orchestrator is not None else "0B",
        },
        "framework": "Python standard library + OpenRouter multi-agent handoffs",
        "runtime": "local Python 3",
        "policy_version": POLICY_VERSION,
        "processed_cases": len(input_files),
        "execution_mode": "openrouter_multi_agent" if orchestrator is not None else "deterministic",
        "llm_calls_per_case": 5 if orchestrator is not None else 0,
    }
    (logging_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(input_files)


def generate_mock_cases(data_dir: Path, input_dir: Path, overwrite: bool = False) -> int:
    """Create 50 reproducible development cases using real Olist order IDs.

    Every generated case is classified by the same policy engine before it is
    written, so it cannot claim an outcome unsupported by the source data.
    """
    input_dir.mkdir(parents=True, exist_ok=True)
    existing = list(input_dir.glob("EC_*.json"))
    if existing and not overwrite:
        raise ValueError("EC input files already exist; refusing to overwrite them.")
    dataset = Dataset.load(data_dir)
    # Six categories cannot receive ten cases each because the assignment has
    # exactly 50 inputs.  This balanced allocation still covers every rule.
    target_counts = {
        "canceled_order_paid": 8,
        "unavailable_order_paid": 8,
        "late_delivery_seller": 9,
        "late_delivery_logistics": 9,
        "valid_split_payment": 8,
        "unsupported_late_claim": 8,
    }
    selections: dict[str, list[str]] = {issue: [] for issue in POLICY_ORDER}
    used: set[str] = set()
    for order_id in sorted(dataset.orders):
        try:
            issue = policy_agent(collect_facts(dataset, order_id))
        except ValueError:
            continue
        if issue in selections and len(selections[issue]) < target_counts[issue] and order_id not in used:
            selections[issue].append(order_id)
            used.add(order_id)
        if all(len(order_ids) == target_counts[issue] for issue, order_ids in selections.items()):
            break
    shortages = {
        issue: len(order_ids)
        for issue, order_ids in selections.items()
        if len(order_ids) < target_counts[issue]
    }
    if shortages:
        raise ValueError(f"Cannot create 50 balanced mock cases; category counts: {shortages}")

    flat = [order_id for issue in POLICY_ORDER for order_id in selections[issue]]
    for number, order_id in enumerate(flat, start=1):
        case = {
            "case_id": f"EC_{number:03d}",
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Vui lòng kiểm tra đơn hàng, nguyên nhân và quyền lợi phù hợp.",
                "claimed_order_id": order_id,
            },
            "policy_version": POLICY_VERSION,
            "mock_case": True,
        }
        (input_dir / f"EC_{number:03d}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return len(flat)
