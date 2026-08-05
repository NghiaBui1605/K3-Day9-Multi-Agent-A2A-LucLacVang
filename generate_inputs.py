"""
generate_inputs.py
Generates 50 diverse input case files (EC_001.json – EC_050.json) from the Olist dataset.

Distribution of cases:
  - 10 canceled_order_paid (order_status=canceled, payment>0)
  - 10 unavailable_order_paid (order_status=unavailable, payment>0)
  - 10 late_delivery_seller (delivered late + seller handoff late)
  - 10 late_delivery_logistics (delivered late + seller on time)
  - 5  valid_split_payment (2+ payment rows, normal order)
  - 5  unsupported_late_claim (delivered on time, normal payment)
"""

import json
import random
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
INPUT_DIR = Path("input")
SEED = 42
random.seed(SEED)


COMPLAINT_TEMPLATES = {
    "late_delivery": [
        "Don hang cua toi co dau hieu giao tre. Hay kiem tra nguyen nhan va quyen loi phu hop.",
        "Toi dat hang tu lau nhung van chua nhan duoc. Don hang giao tre hon du kien, mong duoc ho tro.",
        "Hang giao cham so voi ngay du kien. Toi muon biet ly do va duoc boi thuong phi van chuyen.",
        "Don cua toi bi giao tre qua nhieu ngay. De nghi xem xet hoan phi ship.",
        "Don hang toi muon hon cam ket. Yeu cau kiem tra va hoan tien van chuyen neu co loi.",
    ],
    "canceled": [
        "Don hang cua toi bi huy nhung toi da thanh toan. De nghi hoan tien.",
        "Toi thay don bi cancel nhung tien van bi tru. Yeu cau hoan lai toan bo.",
        "Don bi huy sau khi thanh toan thanh cong. Mong duoc hoan tien gap.",
        "Don hang bi huy ma toi van bi tru tien. Can xu ly hoan tien ngay.",
        "Don bi huy nhung he thong da ghi nhan thanh toan. Yeu cau hoan tra.",
    ],
    "unavailable": [
        "Don hang hien thi trang thai khong kha dung nhung toi da tra tien. Can hoan tra.",
        "He thong bao don unavailable nhung tien da bi tru. Yeu cau hoan tien.",
        "Don cua toi bi danh dau la unavailable, can xu ly hoan tien toan bo.",
    ],
    "payment": [
        "Toi thanh toan nhieu lan cho don nay, khong ro co bi tru hai lan khong. Kiem tra giup toi.",
        "Toi thay co nhieu giao dich cho cung mot don. Xac nhan thanh toan co dung khong?",
        "Don cua toi co ve duoc thanh toan chia nhieu phan. Mong xac nhan tong so tien.",
    ],
    "general": [
        "Toi muon kiem tra trang thai va quyen loi cua don hang nay.",
        "Co van de voi don hang cua toi, mong duoc ho tro dieu tra.",
        "Don hang co ve bat thuong. Nho kiem tra va thong bao ket qua.",
    ],
}


def get_message(issue_type: str) -> str:
    if issue_type in ("late_delivery_seller", "late_delivery_logistics"):
        return random.choice(COMPLAINT_TEMPLATES["late_delivery"])
    elif issue_type == "canceled_order_paid":
        return random.choice(COMPLAINT_TEMPLATES["canceled"])
    elif issue_type == "unavailable_order_paid":
        return random.choice(COMPLAINT_TEMPLATES["unavailable"])
    elif issue_type == "valid_split_payment":
        return random.choice(COMPLAINT_TEMPLATES["payment"])
    else:
        return random.choice(COMPLAINT_TEMPLATES["general"])


def main():
    INPUT_DIR.mkdir(exist_ok=True)

    print("Loading datasets...")
    orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv", low_memory=False)
    payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv", low_memory=False)
    items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv", low_memory=False)

    orders['delivered_dt'] = pd.to_datetime(orders['order_delivered_customer_date'], errors='coerce')
    orders['estimated_dt'] = pd.to_datetime(orders['order_estimated_delivery_date'], errors='coerce')
    orders['carrier_dt'] = pd.to_datetime(orders['order_delivered_carrier_date'], errors='coerce')
    items['shipping_limit_dt'] = pd.to_datetime(items['shipping_limit_date'], errors='coerce')

    # ── Category 1: canceled_order_paid ────────────────────────────────────────
    canceled_ids = set(orders[orders['order_status'] == 'canceled']['order_id'])
    pmt_sums = payments.groupby('order_id')['payment_value'].sum()
    canceled_paid_ids = list(pmt_sums[(pmt_sums.index.isin(canceled_ids)) & (pmt_sums > 0)].index)
    random.shuffle(canceled_paid_ids)
    canceled_sample = canceled_paid_ids[:10]

    # ── Category 2: unavailable_order_paid ─────────────────────────────────────
    unavail_ids = set(orders[orders['order_status'] == 'unavailable']['order_id'])
    unavail_paid_ids = list(pmt_sums[(pmt_sums.index.isin(unavail_ids)) & (pmt_sums > 0)].index)
    random.shuffle(unavail_paid_ids)
    unavail_sample = unavail_paid_ids[:10]

    # ── Category 3 & 4: late delivery ─────────────────────────────────────────
    late_orders = orders[orders['delivered_dt'] > orders['estimated_dt']].copy()

    # Join with items to find seller handoff
    orders_items = orders.merge(
        items[['order_id', 'seller_id', 'shipping_limit_dt']], on='order_id', how='left'
    )
    late_handoff_ids = set(
        orders_items[orders_items['carrier_dt'] > orders_items['shipping_limit_dt']]['order_id']
    )

    late_seller_ids = list(
        late_orders[late_orders['order_id'].isin(late_handoff_ids)]['order_id'].unique()
    )
    late_logistics_ids = list(
        late_orders[~late_orders['order_id'].isin(late_handoff_ids)]['order_id'].unique()
    )

    random.shuffle(late_seller_ids)
    random.shuffle(late_logistics_ids)
    late_seller_sample = late_seller_ids[:10]
    late_logistics_sample = late_logistics_ids[:10]

    # ── Category 5: valid_split_payment ────────────────────────────────────────
    split_counts = payments.groupby('order_id').size()
    split_ids = list(split_counts[split_counts >= 2].index)
    # Only delivered orders
    delivered_ids = set(orders[orders['order_status'] == 'delivered']['order_id'])
    split_delivered = [oid for oid in split_ids if oid in delivered_ids]
    random.shuffle(split_delivered)
    split_sample = split_delivered[:5]

    # ── Category 6: unsupported_late_claim ─────────────────────────────────────
    on_time = orders[
        (orders['order_status'] == 'delivered') &
        (~orders['order_id'].isin(late_handoff_ids)) &
        (orders['delivered_dt'] <= orders['estimated_dt'])
    ]['order_id'].tolist()
    random.shuffle(on_time)
    normal_sample = on_time[:5]

    # ── Assemble all 50 cases ──────────────────────────────────────────────────
    all_cases = (
        [(oid, "canceled_order_paid") for oid in canceled_sample] +
        [(oid, "unavailable_order_paid") for oid in unavail_sample] +
        [(oid, "late_delivery_seller") for oid in late_seller_sample] +
        [(oid, "late_delivery_logistics") for oid in late_logistics_sample] +
        [(oid, "valid_split_payment") for oid in split_sample] +
        [(oid, "unsupported_late_claim") for oid in normal_sample]
    )

    # Shuffle case order so issue type isn't predictable from case ID
    random.shuffle(all_cases)

    print(f"Total cases to generate: {len(all_cases)}")
    for i, (order_id, issue_type) in enumerate(all_cases, start=1):
        case_id = f"EC_{i:03d}"
        message = get_message(issue_type)

        case = {
            "case_id": case_id,
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": message,
                "claimed_order_id": order_id,
            },
            "policy_version": "EC_POLICY_V1",
            "_expected_issue": issue_type,  # debug hint (not in grading schema)
        }

        out_path = INPUT_DIR / f"{case_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(case, f, indent=2, ensure_ascii=False)

        print(f"  {case_id}.json -> {order_id} [{issue_type}]")

    print(f"\nDone! Generated {len(all_cases)} input files in {INPUT_DIR}/")


if __name__ == "__main__":
    main()
