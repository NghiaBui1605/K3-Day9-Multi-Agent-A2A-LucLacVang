# Multi-agent dispute-resolution architecture

The implementation supports real LLM specialist handoffs through OpenRouter,
with a deterministic policy engine and verifier as safety boundaries. This
lets agents analyze and communicate while preventing claims from being
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

The first three Qwen3-8B agents receive scoped facts whose fields originate in
CSV rows. Their JSON handoffs go to the Qwen3-8B Policy Agent and then the
Coordinator. The deterministic policy engine and Verifier check structural
limits, source IDs, money and the EC_POLICY_V1 decision before writing a case
output. `logging/trace.jsonl` records the real model, handoffs and coordinator
response for each OpenRouter run; it is overwritten rather than appended.

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
`qwen/qwen3-8b` (8.2B parameters). The model agents have
no direct CSV or write access; deterministic facts and the verifier remain the
source of truth. If OpenRouter is unavailable, the local verified report is
returned instead.
