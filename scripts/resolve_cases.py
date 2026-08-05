import csv
import json
import os
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
LOGGING_DIR = ROOT / "logging"

DEFAULT_OPENROUTER_MODEL = "qwen/qwen-2.5-7b-instruct"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
POLICY_VERSION = "EC_POLICY_V1"


def load_env(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def configured_model():
    return (
        os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
        or DEFAULT_OPENROUTER_MODEL
    )


def model_parameter_status(model_name):
    known_open_weight = {
        "qwen/qwen-2.5-7b-instruct": ("7B", True),
        "qwen/qwen2.5-7b-instruct": ("7B", True),
        "mistralai/mistral-7b-instruct": ("7B", True),
        "meta-llama/llama-3.1-8b-instruct": ("8B", True),
        "meta-llama/llama-3.1-8b-instant": ("8B", True),
        "gpt-oss-20b": ("20B", False),
        "gpt-oss-120b": ("120B", False),
    }
    normalized = model_name.lower()
    if normalized in known_open_weight:
        parameter_size, under_10b = known_open_weight[normalized]
        return parameter_size, under_10b
    return "undisclosed", None


def parse_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def money(value):
    return Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_float(value):
    return float(money(value))


def load_csv_by_key(path, key):
    rows = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows[row[key]].append(row)
    return rows


def load_orders(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["order_id"]: row for row in csv.DictReader(handle)}


def payment_matches(items, payments):
    item_total = sum(money(row["price"]) for row in items)
    freight_total = sum(money(row["freight_value"]) for row in items)
    payment_total = sum(money(row["payment_value"]) for row in payments)
    return abs(payment_total - item_total - freight_total) <= Decimal("0.10")


def financials(items, payments, refund):
    item_total = sum(money(row["price"]) for row in items)
    freight_total = sum(money(row["freight_value"]) for row in items)
    payment_total = sum(money(row["payment_value"]) for row in payments)
    return {
        "currency": "BRL",
        "item_total_brl": money_float(item_total),
        "freight_total_brl": money_float(freight_total),
        "payment_total_brl": money_float(payment_total),
        "recommended_refund_brl": money_float(refund),
    }


def compact(values, limit):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
        if len(result) == limit:
            break
    return result


def evidence_ids(order_id, items, payments, seller_ids, cause_code):
    ids = [f"order:{order_id}"]
    ids.extend(f"item:{row['order_id']}:{row['order_item_id']}" for row in items)
    ids.extend(f"payment:{row['order_id']}:{row['payment_sequential']}" for row in payments)
    ids.extend(f"seller:{seller_id}" for seller_id in seller_ids)
    ids.append(f"policy:{cause_code}")
    return compact(ids, 10)


class OrderSellerAgent:
    name = "order_seller_agent"

    def analyze(self, order, items):
        carrier_date = parse_datetime(order.get("order_delivered_carrier_date"))
        seller_handoff_late_items = []
        seller_ids = []
        for item in items:
            limit_date = parse_datetime(item.get("shipping_limit_date"))
            if carrier_date and limit_date and carrier_date > limit_date:
                seller_handoff_late_items.append(item)
                seller_ids.append(item["seller_id"])
        return {
            "order_status": order.get("order_status"),
            "seller_ids": compact((item["seller_id"] for item in items), 5),
            "seller_handoff_late_items": seller_handoff_late_items,
            "seller_handoff_late_seller_ids": compact(seller_ids, 3),
        }


class PaymentAgent:
    name = "payment_agent"

    def analyze(self, items, payments):
        item_total = sum(money(row["price"]) for row in items)
        freight_total = sum(money(row["freight_value"]) for row in items)
        payment_total = sum(money(row["payment_value"]) for row in payments)
        reconciled = abs(payment_total - item_total - freight_total) <= Decimal("0.10")
        return {
            "payment_total": payment_total,
            "item_total": item_total,
            "freight_total": freight_total,
            "payment_count": len(payments),
            "payment_reconciled": reconciled,
        }


class DeliveryAgent:
    name = "delivery_agent"

    def analyze(self, order):
        delivered_date = parse_datetime(order.get("order_delivered_customer_date"))
        estimated_date = parse_datetime(order.get("order_estimated_delivery_date"))
        delivered_late = bool(delivered_date and estimated_date and delivered_date > estimated_date)
        delivered_within_estimate = bool(
            delivered_date and estimated_date and delivered_date <= estimated_date
        )
        return {
            "delivered_late": delivered_late,
            "delivered_within_estimate": delivered_within_estimate,
        }


class PolicyAgent:
    name = "policy_agent"

    def decide(self, order_seller, payment, delivery):
        status = order_seller["order_status"]
        if status == "canceled" and payment["payment_total"] > 0:
            return {
                "primary_issue": "canceled_order_paid",
                "cause_code": "ORDER_CANCELED_AFTER_PAYMENT",
                "party_type": "platform",
                "party_id": "OLIST_PLATFORM",
                "refund": payment["payment_total"],
                "action": "issue_full_refund",
                "confidence": 0.99,
            }
        if status == "unavailable" and payment["payment_total"] > 0:
            return {
                "primary_issue": "unavailable_order_paid",
                "cause_code": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                "party_type": "platform",
                "party_id": "OLIST_PLATFORM",
                "refund": payment["payment_total"],
                "action": "issue_full_refund",
                "confidence": 0.99,
            }
        if delivery["delivered_late"] and order_seller["seller_handoff_late_items"]:
            return {
                "primary_issue": "late_delivery_seller",
                "cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
                "party_type": "seller",
                "party_id": order_seller["seller_handoff_late_seller_ids"][0],
                "refund": payment["freight_total"],
                "action": "refund_freight",
                "confidence": 0.94,
            }
        if delivery["delivered_late"]:
            return {
                "primary_issue": "late_delivery_logistics",
                "cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "party_type": "logistics_provider",
                "party_id": "LOGISTICS_PROVIDER",
                "refund": payment["freight_total"],
                "action": "refund_freight",
                "confidence": 0.94,
            }
        if payment["payment_count"] >= 2 and payment["payment_reconciled"]:
            return {
                "primary_issue": "valid_split_payment",
                "cause_code": "MULTIPLE_PAYMENTS_RECONCILED",
                "party_type": None,
                "party_id": None,
                "refund": Decimal("0.00"),
                "action": "explain_valid_split_payment",
                "confidence": 0.92,
            }
        if delivery["delivered_within_estimate"] and payment["payment_reconciled"]:
            return {
                "primary_issue": "unsupported_late_claim",
                "cause_code": "DELIVERY_WITHIN_ESTIMATE",
                "party_type": None,
                "party_id": None,
                "refund": Decimal("0.00"),
                "action": "reject_late_refund",
                "confidence": 0.91,
            }
        return {
            "primary_issue": "unsupported_late_claim",
            "cause_code": "DELIVERY_WITHIN_ESTIMATE",
            "party_type": None,
            "party_id": None,
            "refund": Decimal("0.00"),
            "action": "reject_late_refund",
            "confidence": 0.55,
        }


class OpenRouterPolicyAgent:
    name = "openrouter_policy_agent"

    def __init__(self, model_name, api_key):
        self.model_name = model_name
        self.api_key = api_key

    @property
    def enabled(self):
        return bool(self.api_key and not self.api_key.startswith("your_"))

    def decide(self, case, order_seller, payment, delivery):
        if not self.enabled:
            return None, {"used": False, "reason": "OPENROUTER_API_KEY missing or placeholder"}

        facts = {
            "case_id": case["case_id"],
            "policy_version": case.get("policy_version", POLICY_VERSION),
            "order_status": order_seller["order_status"],
            "seller_handoff_late": bool(order_seller["seller_handoff_late_items"]),
            "seller_handoff_late_seller_ids": order_seller["seller_handoff_late_seller_ids"],
            "delivered_late": delivery["delivered_late"],
            "delivered_within_estimate": delivery["delivered_within_estimate"],
            "payment_total_brl": money_float(payment["payment_total"]),
            "freight_total_brl": money_float(payment["freight_total"]),
            "payment_count": payment["payment_count"],
            "payment_reconciled": payment["payment_reconciled"],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Policy Agent for EC_POLICY_V1. Return only JSON. "
                    "Apply the policy priority order exactly and return the exact strings "
                    "from the policy mapping. primary_issue must be one of the exact "
                    "primary_issue enum values, never a cause_code. valid_split_payment is "
                    "false unless payment_count is at least 2. payment_reconciled alone is "
                    "not enough. Do not invent evidence, money, IDs, or events."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "facts": facts,
                        "primary_issue_enum": [
                            "canceled_order_paid",
                            "unavailable_order_paid",
                            "late_delivery_seller",
                            "late_delivery_logistics",
                            "valid_split_payment",
                            "unsupported_late_claim",
                        ],
                        "selection_instruction": (
                            "Evaluate each policy_priority_order row from top to bottom. "
                            "Return the first row whose condition is true. If payment_count "
                            "is 1, valid_split_payment is not eligible even when "
                            "payment_reconciled is true."
                        ),
                        "policy_priority_order": [
                            {
                                "primary_issue": "canceled_order_paid",
                                "condition": "order_status is canceled and payment_total_brl > 0",
                                "cause_code": "ORDER_CANCELED_AFTER_PAYMENT",
                                "party_type": "platform",
                                "party_id": "OLIST_PLATFORM",
                                "action": "issue_full_refund",
                            },
                            {
                                "primary_issue": "unavailable_order_paid",
                                "condition": "order_status is unavailable and payment_total_brl > 0",
                                "cause_code": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                                "party_type": "platform",
                                "party_id": "OLIST_PLATFORM",
                                "action": "issue_full_refund",
                            },
                            {
                                "primary_issue": "late_delivery_seller",
                                "condition": "delivered_late is true and seller_handoff_late is true",
                                "cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
                                "party_type": "seller",
                                "party_id": "first seller_handoff_late_seller_ids value",
                                "action": "refund_freight",
                            },
                            {
                                "primary_issue": "late_delivery_logistics",
                                "condition": "delivered_late is true and seller_handoff_late is false",
                                "cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
                                "party_type": "logistics_provider",
                                "party_id": "LOGISTICS_PROVIDER",
                                "action": "refund_freight",
                            },
                            {
                                "primary_issue": "valid_split_payment",
                                "condition": "payment_count >= 2 and payment_reconciled is true",
                                "cause_code": "MULTIPLE_PAYMENTS_RECONCILED",
                                "party_type": None,
                                "party_id": None,
                                "action": "explain_valid_split_payment",
                            },
                            {
                                "primary_issue": "unsupported_late_claim",
                                "condition": "delivered_within_estimate is true and payment_reconciled is true",
                                "cause_code": "DELIVERY_WITHIN_ESTIMATE",
                                "party_type": None,
                                "party_id": None,
                                "action": "reject_late_refund",
                            },
                        ],
                        "required_json_schema": {
                            "primary_issue": "string",
                            "cause_code": "string",
                            "party_type": "seller|platform|logistics_provider|null",
                            "party_id": "string|null",
                            "action": "string",
                            "confidence": "number between 0 and 1",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            OPENROUTER_CHAT_COMPLETIONS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost/olist-dispute-resolution",
                "X-Title": "Olist Dispute Resolution Lab",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, {"used": False, "model": self.model_name, "error": detail[:500]}
        except Exception as exc:
            return None, {"used": False, "model": self.model_name, "error": str(exc)}

        response_payload = json.loads(raw)
        content = response_payload["choices"][0]["message"]["content"]
        decision = json.loads(content)
        return decision, {
            "used": True,
            "model": self.model_name,
            "response_id": response_payload.get("id"),
            "finish_reason": response_payload["choices"][0].get("finish_reason"),
        }


class VerifierAgent:
    name = "verifier_agent"

    def build_output(self, case, order, items, payments, order_seller, decision):
        order_id = order["order_id"]
        if decision["primary_issue"] == "late_delivery_seller":
            evidence_items = decision_items = order_seller["seller_handoff_late_items"]
            seller_ids = order_seller["seller_handoff_late_seller_ids"]
        else:
            evidence_items = decision_items = items
            seller_ids = order_seller["seller_ids"]

        item_ids = compact((f"{row['order_id']}:{row['order_item_id']}" for row in decision_items), 5)
        payment_ids = compact((f"{row['order_id']}:{row['payment_sequential']}" for row in payments), 5)

        responsible_parties = []
        if decision["party_type"]:
            responsible_parties.append(
                {"party_type": decision["party_type"], "party_id": decision["party_id"]}
            )

        return {
            "case_id": case["case_id"],
            "assessment": {
                "primary_issue": decision["primary_issue"],
                "case_status": "action_required"
                if decision["refund"] > 0
                else "no_action",
                "confidence": decision["confidence"],
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": decision["cause_code"], "rank": 1}],
                "responsible_parties": responsible_parties,
            },
            "evidence_ids": evidence_ids(
                order_id,
                evidence_items,
                payments,
                seller_ids if decision["party_type"] == "seller" else [],
                decision["cause_code"],
            ),
            "financial_resolution": financials(items, payments, decision["refund"]),
            "resolution_actions": [decision["action"]],
        }


def normalize_llm_decision(llm_decision, deterministic_decision):
    if not llm_decision:
        return deterministic_decision, "deterministic_no_llm"
    comparable_fields = ["primary_issue", "cause_code", "party_type", "party_id", "action"]
    mismatches = [
        field
        for field in comparable_fields
        if llm_decision.get(field) != deterministic_decision.get(field)
    ]
    if mismatches:
        return deterministic_decision, "deterministic_verifier_override:" + ",".join(mismatches)
    decision = dict(deterministic_decision)
    confidence = llm_decision.get("confidence", deterministic_decision["confidence"])
    try:
        decision["confidence"] = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        decision["confidence"] = deterministic_decision["confidence"]
    return decision, "llm_verified"


def resolve_case(case, orders, items_by_order, payments_by_order, llm_agent):
    order_id = case["customer_request"]["claimed_order_id"]
    order = orders[order_id]
    items = items_by_order.get(order_id, [])
    payments = payments_by_order.get(order_id, [])

    order_agent = OrderSellerAgent()
    payment_agent = PaymentAgent()
    delivery_agent = DeliveryAgent()
    policy_agent = PolicyAgent()
    verifier_agent = VerifierAgent()

    order_seller = order_agent.analyze(order, items)
    payment = payment_agent.analyze(items, payments)
    delivery = delivery_agent.analyze(order)
    deterministic_decision = policy_agent.decide(order_seller, payment, delivery)
    llm_decision, llm_trace = llm_agent.decide(case, order_seller, payment, delivery)
    decision, policy_source = normalize_llm_decision(llm_decision, deterministic_decision)
    output = verifier_agent.build_output(case, order, items, payments, order_seller, decision)

    trace = {
        "case_id": case["case_id"],
        "order_id": order_id,
        "policy_version": case.get("policy_version", POLICY_VERSION),
        "agents": [
            {"agent": order_agent.name, "handoff": order_seller},
            {
                "agent": payment_agent.name,
                "handoff": {
                    "payment_total_brl": money_float(payment["payment_total"]),
                    "item_total_brl": money_float(payment["item_total"]),
                    "freight_total_brl": money_float(payment["freight_total"]),
                    "payment_count": payment["payment_count"],
                    "payment_reconciled": payment["payment_reconciled"],
                },
            },
            {"agent": delivery_agent.name, "handoff": delivery},
            {
                "agent": llm_agent.name,
                "handoff": {**llm_trace, "decision": llm_decision},
            },
            {
                "agent": policy_agent.name,
                "handoff": {
                    "primary_issue": decision["primary_issue"],
                    "cause_code": decision["cause_code"],
                    "action": decision["action"],
                    "refund_brl": money_float(decision["refund"]),
                    "source": policy_source,
                },
            },
            {
                "agent": verifier_agent.name,
                "handoff": {
                    "schema_ok": True,
                    "evidence_count": len(output["evidence_ids"]),
                    "case_status": output["assessment"]["case_status"],
                },
            },
        ],
    }
    return output, trace


def validate_output(output):
    assert 0 <= output["assessment"]["confidence"] <= 1
    assert len(output["affected_entities"]["order_ids"]) <= 5
    assert len(output["affected_entities"]["item_ids"]) <= 5
    assert len(output["affected_entities"]["seller_ids"]) <= 5
    assert len(output["affected_entities"]["payment_ids"]) <= 5
    assert len(output["evidence_ids"]) <= 10
    assert len(output["root_cause_analysis"]["ranked_causes"]) <= 3
    assert len(output["root_cause_analysis"]["responsible_parties"]) <= 3
    assert len(output["resolution_actions"]) <= 5


def clean_output_dir():
    OUTPUT_DIR.mkdir(exist_ok=True)
    for path in OUTPUT_DIR.glob("EC_*.json"):
        path.unlink()


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_zip():
    zip_path = ROOT / "output.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUTPUT_DIR.glob("EC_*.json")):
            archive.write(path, arcname=path.name)


def main():
    load_env(ROOT / ".env")
    model_name = configured_model()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    llm_agent = OpenRouterPolicyAgent(model_name=model_name, api_key=api_key)

    orders = load_orders(DATA_DIR / "olist_orders_dataset.csv")
    items_by_order = load_csv_by_key(DATA_DIR / "olist_order_items_dataset.csv", "order_id")
    payments_by_order = load_csv_by_key(DATA_DIR / "olist_order_payments_dataset.csv", "order_id")

    clean_output_dir()
    LOGGING_DIR.mkdir(exist_ok=True)

    traces = []
    summaries = defaultdict(int)
    llm_used_count = 0
    verifier_override_count = 0
    for input_path in sorted(INPUT_DIR.glob("EC_*.json")):
        case = json.loads(input_path.read_text(encoding="utf-8"))
        output, trace = resolve_case(case, orders, items_by_order, payments_by_order, llm_agent)
        validate_output(output)
        write_json(OUTPUT_DIR / input_path.name, output)
        traces.append(trace)
        summaries[output["assessment"]["primary_issue"]] += 1
        llm_trace = next(row for row in trace["agents"] if row["agent"] == llm_agent.name)
        policy_trace = next(row for row in trace["agents"] if row["agent"] == "policy_agent")
        if llm_trace["handoff"].get("used"):
            llm_used_count += 1
        if str(policy_trace["handoff"].get("source", "")).startswith("deterministic_verifier_override"):
            verifier_override_count += 1

    trace_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in traces)
    (ROOT / "trace.jsonl").write_text(trace_text, encoding="utf-8")
    (LOGGING_DIR / "trace.jsonl").write_text(trace_text, encoding="utf-8")

    parameter_size, under_10b = model_parameter_status(model_name)
    metadata = {
        "model": model_name,
        "parameter_size": parameter_size,
        "under_10b_parameters": under_10b,
        "provider": "OpenRouter",
        "parameter_note": "OpenRouter model slug uses Qwen2.5 7B Instruct by default; under_10b is true for known <=10B open-weight slugs in this pipeline.",
        "framework": "Python 3.12 standard library, OpenRouter policy agent with deterministic verifier",
        "runtime": {
            "language": "python",
            "policy_version": POLICY_VERSION,
            "case_count": len(traces),
            "openrouter_api_used_cases": llm_used_count,
            "verifier_override_count": verifier_override_count,
            "output_dir": "output",
            "trace_file": "trace.jsonl",
        },
        "issue_distribution": dict(sorted(summaries.items())),
    }
    write_json(ROOT / "metadata.json", metadata)
    write_json(LOGGING_DIR / "metadata.json", metadata)
    write_zip()

    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
