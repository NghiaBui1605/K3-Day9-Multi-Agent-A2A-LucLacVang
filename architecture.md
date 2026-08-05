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
