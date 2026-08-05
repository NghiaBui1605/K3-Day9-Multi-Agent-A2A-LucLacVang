# Architecture – Multi-Agent E-commerce Dispute Resolution

## Overview

This system implements a deterministic multi-agent pipeline for investigating e-commerce customer support cases using the Olist Brazilian E-Commerce dataset. Each agent is a specialized Python class with a single responsibility.

---

## Agent Roles

| Agent | Responsibility | Data Access |
|-------|----------------|-------------|
| **CoordinatorAgent** | Receives input case, dispatches to specialist agents in order, assembles final output JSON, hands off to VerifierAgent | None directly |
| **OrderSellerAgent** | Queries order status, items, seller IDs, shipping limit dates, and carrier handoff timestamps | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_sellers_dataset.csv`, `olist_customers_dataset.csv` |
| **PaymentAgent** | Reconciles payment rows against item+freight totals, detects split payments | `olist_order_payments_dataset.csv` |
| **DeliveryAgent** | Compares `order_delivered_customer_date` vs `order_estimated_delivery_date`; `order_delivered_carrier_date` vs `shipping_limit_date` per item | Reads from `order_facts` (passed by Coordinator) |
| **PolicyAgent** | Applies EC_POLICY_V1 business rules in strict priority order, determines primary issue, responsible party, refund amount, and action | Reads from `order_facts`, `payment_facts`, `delivery_facts` |
| **VerifierAgent** | Validates evidence ID formats (regex), enforces entity limits (max 5 IDs, 10 evidence, 3 causes, 5 actions), corrects out-of-range values, writes `output/EC_XXX.json` | None (validates in-memory dict) |

---

## Handoff Flow

```
[Input: input/EC_XXX.json]
          │
          ▼
┌─────────────────────────┐
│     CoordinatorAgent    │  ← Receives case dict
│  (orchestrates pipeline) │
└─────────┬───────────────┘
          │
          ▼ Step 1: dispatch order info
┌─────────────────────────┐
│    OrderSellerAgent     │  → order_facts dict
│  Reads: orders, items,  │    (order_status, items[], seller_ids[],
│  sellers, customers CSV │     timestamps)
└─────────┬───────────────┘
          │ order_facts
          ▼ Step 2: payment reconciliation
┌─────────────────────────┐
│      PaymentAgent       │  → payment_facts dict
│  Reads: payments CSV    │    (total_payment_brl, is_split_payment,
│                         │     payment_reconciled, payment_rows[])
└─────────┬───────────────┘
          │ order_facts + payment_facts
          ▼ Step 3: delivery timing analysis
┌─────────────────────────┐
│      DeliveryAgent      │  → delivery_facts dict
│  (uses order_facts      │    (delivered_late, seller_handoff_late,
│   timestamps only)      │     late_seller_ids[], days_late)
└─────────┬───────────────┘
          │ order_facts + payment_facts + delivery_facts
          ▼ Step 4: policy decision
┌─────────────────────────┐
│       PolicyAgent       │  → policy_decision dict
│  EC_POLICY_V1 rules     │    (primary_issue, root_cause_code,
│  in priority order      │     responsible_parties[], refund, action)
└─────────┬───────────────┘
          │ all facts + policy_decision
          ▼ Step 5: assemble + validate + write
┌─────────────────────────┐
│     VerifierAgent       │  → writes output/EC_XXX.json
│  Validates schema,      │    Returns (validated_output, warnings[])
│  evidence IDs, amounts  │
└─────────────────────────┘
          │
          ▼
[Output: output/EC_XXX.json + trace.jsonl]
```

---

## Policy Priority Order (EC_POLICY_V1)

Rules are applied in this exact order; first match wins:

1. `canceled_order_paid` – `order_status = canceled` AND `total_payment > 0`
2. `unavailable_order_paid` – `order_status = unavailable` AND `total_payment > 0`
3. `late_delivery_seller` – delivered after estimated AND carrier received after `shipping_limit_date`
4. `late_delivery_logistics` – delivered after estimated AND carrier received on time
5. `valid_split_payment` – 2+ payment rows AND `total_payment ≈ item + freight (±0.10 BRL)`
6. `unsupported_late_claim` – default fallback

---

## Data Layer

All CSV access goes through `agents/data_loader.py`, which uses `@lru_cache` to load each CSV exactly once per process run. Agents receive structured Python dicts, not raw DataFrames.

```
agents/data_loader.py
  ├── get_order(order_id)          → dict | None
  ├── get_order_items(order_id)    → list[dict]
  ├── get_order_payments(order_id) → list[dict]
  ├── get_seller(seller_id)        → dict | None
  └── get_customer(customer_id)    → dict | None
```

---

## Evidence ID Format

Only IDs derivable directly from CSV data are submitted:

| Format | Example |
|--------|---------|
| `order:<order_id>` | `order:e834a6d9d3cea0c687c250fc654a0232` |
| `item:<order_id>:<order_item_id>` | `item:e834a6d9d3cea0c687c250fc654a0232:1` |
| `payment:<order_id>:<payment_sequential>` | `payment:e834a6d9d3cea0c687c250fc654a0232:1` |
| `seller:<seller_id>` | `seller:2a1348e9addc1af5aaa619b1a3679d6b` |
| `policy:<root_cause_code>` | `policy:ORDER_CANCELED_AFTER_PAYMENT` |

VerifierAgent validates all IDs with regex before writing output.

---

## File Structure

```
K3-Day9-Multi-Agent-A2A/
├── agents/
│   ├── __init__.py
│   ├── data_loader.py          ← shared CSV cache
│   ├── coordinator.py          ← orchestrator
│   ├── order_seller_agent.py   ← order & seller domain
│   ├── payment_agent.py        ← payment domain
│   ├── delivery_agent.py       ← delivery timing domain
│   ├── policy_agent.py         ← policy engine
│   └── verifier_agent.py       ← schema validator & writer
├── data/                       ← 9 Olist CSV files
├── input/                      ← EC_001.json … EC_050.json
├── output/                     ← EC_001.json … EC_050.json (results)
├── logging/                    ← run.log
├── generate_inputs.py          ← generates diverse 50 input cases
├── analyze_data.py             ← data exploration script
├── main.py                     ← runner (--dry-run, --case EC_XXX)
├── trace.jsonl                 ← per-case trace of all agent steps
├── metadata.json               ← model, framework, runtime info
├── architecture.md             ← this file
└── README.md
```

---

## Runtime

- **Language**: Python 3.14
- **Libraries**: pandas 3.0.5 (data), standard library (json, logging, re, datetime)
- **Model**: Rule-based deterministic (no LLM) — all decisions are data-driven per EC_POLICY_V1
- **Performance**: ~7 seconds for all 50 cases (CSV loaded once, cached)
- **Tracing**: Every agent step is logged to `trace.jsonl` with elapsed time and result summary
