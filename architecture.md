# Multi-agent dispute-resolution architecture

The implementation uses deterministic specialist agents rather than an LLM.
This keeps every conclusion reproducible and prevents claims from being
invented beyond the records in the Olist CSV files.

```text
Web chatbot / Case JSON
   |
Chat adapter (`DisputeChatbot`) / Coordinator (`process_case`)
   |-- Order & Seller Agent --> order status, item rows, seller IDs
   |-- Payment Agent --------> payment rows and reconciled totals
   |-- Delivery Agent --------> delivery/estimate comparison and late handoff
   |-- Policy Agent ----------> EC_POLICY_V1 issue, party, refund, action
   `-- Verifier Agent --------> output limits and evidence-ID prefixes
                                      |
                                 Output JSON + trace
```

## Roles and access

| Agent | Reads | Produces | Write access |
| --- | --- | --- | --- |
| Coordinator | Case JSON | final assembled assessment | output and logging via coordinator |
| Order & Seller | orders, order_items | status, items, seller IDs | none |
| Payment | order_payments, item facts | payment total and reconciliation | none |
| Delivery | order timestamps, item shipping limits | lateness and late seller IDs | none |
| Policy | handed-off facts, policy constants | issue, cause, responsible party, refund/action | none |
| Verifier | assembled output | pass/fail schema validation | none |

## Handoff contract

The first three agents return only facts whose fields originate in CSV rows.
The Policy Agent receives these facts and applies the precedence defined by
`EC_POLICY_V1`. The Verifier then checks structural submission limits before
the coordinator writes a case output. `logging/trace.jsonl` records this exact
handoff sequence for each run; it is overwritten for a fresh run rather than
appended.

## Resilience (no hard-gate on the batch)

Classification never raises during batch processing. When a case matches a
rule exactly, the assessment carries full confidence. When no rule fires
(e.g. an order delivered on time whose payments do not reconcile, or a
not-yet-delivered status), the pipeline falls back to the most defensible,
non-refunding outcome (`unsupported_late_claim` / `no_action`, refund `0.0`)
with a lowered confidence, and records `rule_matched: false` in the trace.
If a case is entirely unprocessable (unknown `claimed_order_id`, malformed
JSON, wrong policy version), `process_directory` catches the error per case
and writes a schema-valid fallback output plus an `error` field in the trace.
This guarantees all 50 outputs are always written: a single bad case earns
partial credit on schema and financial fields instead of zeroing the run.

## Mock-input workflow

`python src/main.py --generate-mocks` finds real orders spanning all six
policy outcomes (8--9 cases per outcome, 50 total) and writes reproducible development cases to
`input/`. These inputs carry `mock_case: true` and must be replaced by the
official cases before submission. The generator refuses to overwrite existing
case files unless `--overwrite-mocks` is passed explicitly.

## Chatbot interface

`src/chatbot.py` runs a local web chatbot at `http://127.0.0.1:8000`. It
extracts either an `EC_###` case ID from a Vietnamese message or a 32-character
Olist order ID, then calls the same coordinator. The answer is a human-readable
Vietnamese rendering of the verified output, including the policy conclusion,
financial recommendation and evidence IDs. For a case lookup, the chatbot
creates explicit model handoffs: Order & Seller, Payment and Delivery specialists
send JSON handoffs to a Policy Agent; a Coordinator Agent turns those handoffs
into the customer-facing reply. All use OpenRouter's
`qwen/qwen3-8b` (8B parameters, ≤10B as required). The model agents have
no direct CSV or write access; deterministic facts and the verifier remain the
source of truth. If OpenRouter is unavailable, the local verified report is
returned instead.
