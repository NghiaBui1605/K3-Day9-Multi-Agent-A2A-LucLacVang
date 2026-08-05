# Member Role Report: Day 9 Multi-Agent A2A

## 1. Thong tin ca nhan

| Thong tin | Noi dung |
| --- | --- |
| Ho va ten | HoVaTen can cap nhat |
| MSSV | 5SoCuoiMHV can cap nhat |
| Khoa/Lop | K3 |
| Vai tro chinh | Pipeline, policy agent va verifier |
| Ngay hoan thanh | 2026-08-05 |

## 2. Vai tro va pham vi cong viec

| Module/deliverable | File/ham phu trach | Input nhan vao | Output ban giao | Trang thai |
| --- | --- | --- | --- | --- |
| Multi-agent pipeline | `scripts/resolve_cases.py` | 50 file `input/EC_*.json`, 3 CSV chinh: orders, items, payments | 50 file `output/EC_*.json` | Hoan thanh |
| Trace va metadata | `scripts/resolve_cases.py`, `trace.jsonl`, `metadata.json` | Handoff cua tung agent | Trace 50 case, thong tin model/runtime | Hoan thanh |
| Kien truc he thong | `architecture.md` | Policy trong README va thiet ke pipeline | Mo ta agent, vai tro, handoff, verifier | Hoan thanh |

## 3. Ket qua theo vai tro

| Nhiem vu | Artifact lien quan | Ket qua ban giao | Cach xac minh |
| --- | --- | --- | --- |
| Sinh output theo schema | `output/EC_001.json` den `output/EC_050.json` | Du 50 JSON, moi file khop ten input | `(Get-ChildItem output -Filter EC_*.json).Count` tra ve 50 |
| Ap dung policy theo thu tu uu tien | `scripts/resolve_cases.py` | Phan loai 6 issue trong README | `python scripts\resolve_cases.py` in issue distribution |
| Dong goi bai nop | `output.zip` | Zip chi chua 50 JSON output | `python -m zipfile -l output.zip` |

Artifact chinh la bo 50 ket qua trong `output/`, kem `trace.jsonl` de giai thich quy trinh xu ly tung case.

## 4. Giai thich ky thuat

### Van de can giai quyet

Moi khieu nai chi co `claimed_order_id`, trong khi ket luan can doi chieu trang thai order, moc seller ban giao, ngay giao thuc te, tong item/freight va cac dong payment. Pipeline can tao ket qua co evidence ID hop le va so tien refund dung policy.

### Cach trien khai

He thong dung cac class agent rieng:

- `OrderSellerAgent` doc order/item, xac dinh seller va item co `order_delivered_carrier_date > shipping_limit_date`.
- `PaymentAgent` tinh tong tien va doi soat split payment voi sai so 0.10 BRL.
- `DeliveryAgent` so sanh ngay giao thuc te voi ngay giao uoc tinh.
- `PolicyAgent` ap dung 6 rule theo thu tu uu tien trong README.
- `VerifierAgent` tao schema output, gioi han entity/evidence va lam tron tien 2 chu so.

### Input, output va contract

| Thanh phan | Mo ta |
| --- | --- |
| Input | `input/EC_*.json`, `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_order_payments_dataset.csv` |
| Output | JSON theo schema README trong `output/`, trace JSONL, metadata JSON |
| Module phu thuoc | Python 3.12 standard library: `csv`, `json`, `decimal`, `zipfile` |
| Module su dung output | Verifier va zip packager |
| Dieu kien loi can xu ly | Don khong co item row, nhieu payment row, nhieu item, order canceled/unavailable da thanh toan |

### Cach xac minh

```powershell
python scripts\resolve_cases.py
(Get-ChildItem output -Filter EC_*.json).Count
python -m zipfile -l output.zip
```

- Ket qua mong doi: co 50 output JSON, trace 50 dong, zip chi chua `EC_001.json` den `EC_050.json`.
- Ket qua thuc te: script chay thanh cong, dem output tra ve 50, zip list hien 50 file JSON.
- Artifact/log: `output/`, `output.zip`, `trace.jsonl`, `metadata.json`.

## 5. Quyet dinh ky thuat quan trong

- Boi canh: README yeu cau multi-agent nhung policy co dieu kien ro rang va du lieu CSV co cau truc.
- Phuong an can nhac: dung OpenAI proprietary model khong cong bo parameter, hoac dung OpenRouter voi open-weight model co size ro.
- Phuong an da chon: OpenRouter Policy Agent voi `qwen/qwen-2.5-7b-instruct` va Verifier deterministic.
- Ly do: model Qwen2.5 7B co size ro, thoa dieu kien duoi 10B, trong khi verifier van giu ket qua tai lap va khong tao evidence ngoai CSV.
- Bang chung: `metadata.json` ghi provider OpenRouter, model `qwen/qwen-2.5-7b-instruct`, parameter size `7B`, `under_10b_parameters: true`; `trace.jsonl` ghi handoff that cua 50 case.

## 6. Loi hoac blocker da xu ly

- Trieu chung: file bao cao ban dau con template va noi dung khong khop bai Olist.
- Buoc tai hien: mo `individual_5SoCuoiMHV_HoVaTen.md` va thay cau hoi ve Crossref/vector index.
- Nguyen nhan goc: template tu bai lab khac chua duoc cap nhat.
- Cach xu ly: viet lai bao cao theo pipeline Olist A2A va artifact that.
- Cach xac minh: doc lai file bao cao, doi chieu voi `scripts/resolve_cases.py`, `output/`, `trace.jsonl`.
- Dieu hoc duoc: artifact bao cao ca nhan can bam theo pipeline thuc te, khong chi giu template.

## 7. Hieu biet ve luong end-to-end

Du lieu di tu `input/EC_*.json` vao Coordinator bang `claimed_order_id`. Tu khoa nay, cac agent join sang `orders`, `order_items` va `order_payments`. Order/Seller Agent xac dinh trang thai va seller ban giao tre, Payment Agent doi soat tien, Delivery Agent xac dinh giao tre hay dung han. Policy Agent ap dung rule uu tien cua `EC_POLICY_V1`, sau do Verifier Agent tao schema output, evidence ID va so tien refund. Cuoi cung Coordinator ghi output JSON, trace, metadata va zip nop bai.

## 8. Cam ket cua thanh vien

- [x] Noi dung bao cao phan anh dung phan viec va muc hieu cua toi.
- [x] Toi co the giai thich luong end-to-end, khong chi module minh phu trach.
- [x] Toi khong ghi "da chay thanh cong" cho phan chua duoc kiem chung.
- [x] Bao cao khong chua `.env`, API key, token hoac secret.
- [x] Bao cao nay khong phai ban sao nguyen van cua bao cao nhom hoac bao cao thanh vien khac.

**Ho va ten:** HoVaTen can cap nhat
**Ngay xac nhan:** 2026-08-05
