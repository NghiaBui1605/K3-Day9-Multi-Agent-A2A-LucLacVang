# Member Role Report: Day 9 Multi-Agent A2A

## 1. Thong tin ca nhan

| Thong tin       | Noi dung                                                                  |
| --------------- | ------------------------------------------------------------------------- |
| Ho va ten       | La Minh Duc                                                               |
| MSSV            | 2A202601261                                                               |
| Khoa/Lop        | K3                                                                        |
| Vai tro chinh   | Phat trien pipeline multi-agent, chatbot va giao dien theo doi tranh chap |
| Ngay hoan thanh | 2026-08-05                                                                |

## 2. Vai tro va pham vi cong viec

| Module/deliverable               | File/ham phu trach                                             | Input nhan vao                                      | Output ban giao                                                 | Trang thai |
| -------------------------------- | -------------------------------------------------------------- | --------------------------------------------------- | --------------------------------------------------------------- | ---------- |
| Pipeline xu ly tranh chap        | `src/dispute_pipeline.py`: `process_case`, `process_directory` | Case `input/EC_*.json` va CSV Olist                 | JSON danh gia theo `EC_POLICY_V1`, trace va metadata            | Hoan thanh |
| Cac agent chuyen mon va verifier | `src/dispute_pipeline.py`                                      | Du lieu order, item, payment va timestamp giao hang | Handoff fact, ket luan policy, evidence ID va ket qua da verify | Hoan thanh |
| Chatbot A2A                      | `src/chatbot.py`, `src/llm_multi_agent.py`, `src/config.py`    | Tin nhan, `EC_###` hoac Olist order ID              | Phan hoi tieng Viet dua tren ket qua da xac minh                | Hoan thanh |
| Giao dien web                    | `frontend/src/App.tsx`, `frontend/src/index.css`               | Du lieu case va API chatbot                         | Dashboard hien thi tranh chap, evidence va ket qua xu ly        | Hoan thanh |
| Tao input phat trien va audit    | `src/main.py`, `src/audit_groundtruth.py`                      | CSV Olist va 50 case                                | Mock case, doi chieu ground truth va `output.zip`               | Hoan thanh |

## 3. Ket qua theo vai tro

| Nhiem vu                  | Artifact lien quan                         | Ket qua ban giao                                                                                  | Cach xac minh                                                                                 |
| ------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Xay dung policy pipeline  | `src/dispute_pipeline.py`                  | Tach ro Order & Seller, Payment, Delivery, Policy va Verifier Agent                               | Doc `POLICY_ORDER`, `process_case` va `verifier_agent`                                        |
| Xu ly bo case             | `input/`, `output/`, `logging/trace.jsonl` | Co 50 input va 50 output JSON tuong ung; trace ghi chuoi handoff cua tung case                    | `(Get-ChildItem output -Filter EC_*.json).Count` va `(Get-Content logging/trace.jsonl).Count` |
| Bao dam rang buoc bai nop | `verifier_agent`                           | Gioi han entity/evidence, kiem tra prefix evidence va confidence truoc khi ghi output             | Chay `python src/main.py --process`                                                           |
| Xay dung chatbot grounded | `src/chatbot.py`, `src/llm_multi_agent.py` | Nhan ma case/order, goi pipeline va tra ket qua tieng Viet; fallback ve ket qua local khi LLM loi | Chay `python src/chatbot.py`, gui `Kiem tra EC_001`                                           |
| Xay dung frontend         | `frontend/`                                | Ung dung React/Vite hien thi console xu ly tranh chap                                             | `cd frontend; npm run build`                                                                  |

Artifact chinh toi ban giao la ma nguon pipeline co the tai lap, chatbot/giao dien de tra cuu ket qua va bo 50 case dau ra kem trace.

## 4. Giai thich ky thuat

### Van de can giai quyet

Moi khieu nai chi cung cap `claimed_order_id`, trong khi ket luan phai duoc suy ra tu nhieu bang Olist: trang thai don, item va seller, cac dong thanh toan, moc ban giao cho carrier va ngay giao du kien. He thong can ap dung dung thu tu uu tien cua `EC_POLICY_V1`, tinh refund chinh xac va khong tu tao evidence ngoai CSV.

### Cach trien khai

- `Order & Seller Agent` truy xuat order, item va seller lien quan.
- `Payment Agent` cong `price`, `freight_value`, `payment_value`; doi soat payment voi sai so toi da 0.10 BRL.
- `Delivery Agent` so sanh cac timestamp giao hang va tim seller giao cho carrier qua han.
- `Policy Agent` ap dung sau rule theo thu tu uu tien: canceled, unavailable, seller late, logistics late, split payment va claim khong duoc ho tro.
- `Verifier Agent` kiem tra schema, evidence prefix, so luong phan tu, confidence va lam tron tien bang `Decimal` truoc khi luu file.
- Chatbot chi nhan fact packet va canonical assessment. Neu co OpenRouter key, cac specialist LLM tao phan giai thich theo handoff; ket qua policy da verify van la nguon su that. Neu provider khong san sang, chatbot tra ket qua deterministic tai may.

### Input, output va contract

| Thanh phan       | Mo ta                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------ |
| Input            | `input/EC_*.json`; `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_order_payments_dataset.csv` |
| Output           | `output/EC_*.json`, `logging/trace.jsonl`, `logging/metadata.json`                                                 |
| Contract handoff | Cac agent chuyen fact tu CSV; Policy Agent chi chon rule; Verifier la thanh phan duy nhat chap nhan output cuoi    |
| Dieu kien loi    | Khong co order ID, policy version sai, khong co input case, ket qua vuot gioi han schema hoac evidence sai prefix  |

### Cach xac minh

```powershell
python src/main.py --process
(Get-ChildItem output -Filter EC_*.json).Count
(Get-Content logging/trace.jsonl).Count
cd frontend
npm run build
```

- Ket qua mong doi: xu ly 50 case, co 50 output JSON va 50 dong trace; frontend build thanh cong.
- Da doi chieu bang cach xem cac artifact `output/`, `logging/trace.jsonl`, `logging/metadata.json` va cac ham verifier trong source.
- Viec goi OpenRouter khong phai dieu kien de pipeline chay; API key duoc giu trong `.env` va khong dua vao bao cao hay repository.

## 5. Quyet dinh ky thuat quan trong

- **Dung policy deterministic cho ket qua nop bai:** Quy tac va CSV co cau truc, nen ket qua can tai lap va de audit. LLM chi duoc dung de dien dat hoi dap, khong duoc sua issue, refund, action hay evidence.
- **Tach agent theo domain:** Order/Seller, Payment va Delivery chi tra fact trong pham vi du lieu cua minh. Cach tach nay lam ro handoff va giam nguy co mot prompt tu suy dien toan bo ket qua.
- **Verifier truoc khi ghi file:** Kiem tra truoc cac hard gate cua de bai, dac biet la format evidence va gioi han so luong ID.
- **Model cau hinh ro rang:** `src/config.py` khai bao `meta-llama/llama-3.2-3b-instruct` (3B), nam trong gioi han 10B cua bai. Pipeline policy khong phu thuoc model.
- **Mock input co kiem soat:** `--generate-mocks` chi tao case phat trien tu order that va tu choi ghi de khi chua co `--overwrite-mocks`.

## 6. Loi hoac blocker da xu ly

- **Rui ro LLM lam sai ket qua nghiep vu:** Dua ra canonical assessment tu pipeline deterministic va gioi han LLM chi giai thich fact da verify.
- **Rui ro OpenRouter khong san sang:** Bat `HTTPError`/`URLError` va tra ket qua local thay vi lam hong luong chatbot.
- **Rui ro input ma don khong hop le:** Chatbot chi chap nhan `EC_###` ton tai hoac order ID Olist 32 ky tu; pipeline bao loi ro rang khi order khong ton tai.
- **Rui ro output khong dat schema:** `verifier_agent` fail fast truoc khi file output duoc ghi.

## 7. Hieu biet ve luong end-to-end

Nguoi dung gui case ID hoac order ID qua giao dien/chatbot. Coordinator tao case va dua `claimed_order_id` cho Order & Seller Agent, Payment Agent va Delivery Agent. Cac agent chi handoff fact co nguon goc CSV. Policy Agent ap dung `EC_POLICY_V1`; Verifier kiem tra ket qua truoc khi Coordinator tra loi chatbot hoac ghi `output/EC_*.json`. Moi case duoc ghi trace theo thu tu `order_seller -> payment -> delivery -> policy -> verifier`, vi vay co the xem lai qua trinh xu ly ma khong can tin vao noi dung LLM.

## 8. Cam ket cua thanh vien

- [x] Noi dung bao cao phan anh phan viec cua toi: pipeline, chatbot, giao dien va audit artifact.
- [x] Toi co the giai thich luong end-to-end va cac handoff giua cac agent.
- [x] Toi phan biet ro ket qua deterministic da verify voi phan LLM/Provider tuy chon.
- [x] Bao cao khong chua `.env`, API key, token hoac secret.
- [x] Bao cao nay duoc viet theo artifact cua repository, khong phai ban sao nguyen van cua bao cao thanh vien khac.

**Ho va ten:** La Minh Duc  
**Ngay xac nhan:** 2026-08-04
