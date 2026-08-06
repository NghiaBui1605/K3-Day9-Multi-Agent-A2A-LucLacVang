<<<<<<< HEAD
# Multi-Agent Architecture

## Muc tieu

He thong xu ly 50 case khieu nai thuong mai dien tu bang du lieu Olist va policy `EC_POLICY_V1`. Ket qua duoc sinh tu du lieu co the kiem chung trong CSV, khong suy dien refund ledger, tracking checkpoint hay bang chung khong ton tai.

## Agent va pham vi truy cap

| Agent | Vai tro | Du lieu doc | Output handoff |
| --- | --- | --- | --- |
| Coordinator Agent | Doc input case, lay `claimed_order_id`, dieu phoi cac agent va gom trace. | `input/EC_*.json` | `case_id`, `order_id`, `policy_version` |
| Order & Seller Agent | Kiem tra trang thai don, item, seller va moc `shipping_limit_date`. | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv` | `order_status`, seller lien quan, item ban giao tre neu co |
| Payment Agent | Tinh tong item, freight, payment va doi soat split payment. | `olist_order_items_dataset.csv`, `olist_order_payments_dataset.csv` | `item_total`, `freight_total`, `payment_total`, `payment_reconciled` |
| Delivery Agent | So sanh ngay giao thuc te voi ngay giao uoc tinh. | `olist_orders_dataset.csv` | `delivered_late`, `delivered_within_estimate` |
| Policy Agent | Ap dung policy theo thu tu uu tien trong README. | Handoff cua Order/Seller, Payment, Delivery | `primary_issue`, root cause, responsible party, refund, action |
| Verifier Agent | Kiem tra schema, gioi han so luong entity/evidence, dinh dang ID va lam tron tien. | Handoff cua tat ca agent | JSON output cuoi cung |

## Luong handoff

1. Coordinator doc tung file `input/EC_*.json` va lay `claimed_order_id`.
2. Order & Seller Agent join order voi item de xac dinh seller va item co `order_delivered_carrier_date > shipping_limit_date`.
3. Payment Agent tinh tong `price`, `freight_value`, `payment_value`; split payment hop le khi co tu 2 payment row va chenh lech khong qua 0.10 BRL.
4. Delivery Agent so sanh `order_delivered_customer_date` voi `order_estimated_delivery_date`.
5. Policy Agent ap dung thu tu:
   - `canceled_order_paid`
   - `unavailable_order_paid`
   - `late_delivery_seller`
   - `late_delivery_logistics`
   - `valid_split_payment`
   - `unsupported_late_claim`
6. Verifier Agent tao `affected_entities`, `root_cause_analysis`, `evidence_ids`, `financial_resolution`, `resolution_actions`.
7. Coordinator ghi `output/EC_*.json`, `trace.jsonl`, `metadata.json` va `output.zip`.

## Quy tac evidence

Verifier chi ghi cac evidence ID dung dinh dang cho phep:

```text
order:<order_id>
item:<order_id>:<order_item_id>
payment:<order_id>:<payment_sequential>
seller:<seller_id>
policy:<root_cause_code>
```

Moi output gioi han toi da 5 ID trong moi entity set, 10 evidence, 3 root causes, 3 responsible parties va 5 actions. Tien duoc lam tron 2 chu so thap phan bang Decimal.

## Runtime

Pipeline nam trong `scripts/resolve_cases.py`, chay bang Python 3.12 standard library. Policy Agent goi OpenRouter qua endpoint OpenAI-compatible `https://openrouter.ai/api/v1/chat/completions`; mac dinh model la `qwen/qwen-2.5-7b-instruct`, kich thuoc 7B, thoa dieu kien duoi 10B parameters. Verifier Agent van doi chieu deterministic truoc khi ghi output de tranh sai schema, sai evidence hoac sai tien.
=======
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
`meta-llama/llama-3.2-3b-instruct:free` (3B parameters). The model agents have
no direct CSV or write access; deterministic facts and the verifier remain the
source of truth. If OpenRouter is unavailable, the local verified report is
returned instead.
>>>>>>> 3410db2 (Pre code)
