# Báo cáo vai trò cá nhân — Day 9: Multi-Agent A2A

> Trước khi nộp: điền họ tên, MSSV, lớp; đổi tên file theo mẫu yêu cầu và tự đánh dấu phần cam kết.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | [Điền họ và tên] |
| MSSV | [Điền MSSV] |
| Khóa/Lớp | [Điền khóa/lớp] |
| Vai trò chính | Pipeline, Verifier và tích hợp hệ thống |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Policy pipeline | `src/dispute_pipeline.py` | 50 case JSON và CSV Olist | 50 assessment JSON | Hoàn thành |
| Verification | `verifier_agent`, `process_directory` | Assessment và facts từ CSV | Hard-gate schema, ID, tiền và policy | Hoàn thành |
| CLI và audit | `src/main.py`, `logging/` | Thư mục input/data | Output, trace và metadata | Hoàn thành |
| Chatbot integration | `src/chatbot.py`, `src/llm_multi_agent.py` | Case ID/order ID và tin nhắn | Phản hồi tiếng Việt có evidence | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Kiểm tra frontend | React/Vite console | Production build thành công, không có lỗi TypeScript |
| Chuẩn bị artifact nộp | Nhóm | `output.zip` có đúng 50 JSON, không chứa file lạ |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Join order, item và payment | `Dataset.load`, `collect_facts` | Facts có nguồn gốc từ CSV | `python src/main.py --process` |
| Áp dụng thứ tự ưu tiên EC_POLICY_V1 | `policy_agent` | Bao phủ đủ 6 primary issue | Phân bố 8/8/8/8/9/9 trên bộ input chính thức |
| Tạo assessment | `build_assessment` | Entity, cause, party, evidence, financial và action | Đối soát lại với CSV |
| Chặn output không hợp lệ | `verifier_agent` | Kiểm tra giới hạn, ID tồn tại, tổng tiền, refund và policy | Negative test với evidence giả bị từ chối |
| Ghi audit có thể tái lập | `process_directory` | 50 output, 50 trace và metadata mới nhất | Đếm file/dòng sau mỗi lần chạy |

Artifact cụ thể là bộ `output/EC_001.json` đến `output/EC_050.json`. Mỗi kết quả được dựng từ cùng một pipeline quyết định và được Verifier kiểm tra trước khi ghi xuống đĩa.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Một lời khiếu nại không đủ để quyết định hoàn tiền. Pipeline phải nối đúng order với item/seller và payment, so sánh các mốc giao hàng, áp dụng policy theo thứ tự ưu tiên, rồi chỉ xuất bằng chứng có thể truy ngược về CSV.

### Cách triển khai

Coordinator gọi ba specialist độc lập. Order & Seller Agent lấy trạng thái đơn cùng item/seller. Payment Agent dùng `Decimal` để cộng giá item, freight và payment, sau đó đối soát với sai số 0,10 BRL. Delivery Agent so sánh thời gian giao thực tế với estimated date và thời điểm carrier nhận hàng với shipping limit của từng seller.

Policy Agent áp dụng lần lượt canceled, unavailable, late-by-seller, late-by-logistics, valid split payment và unsupported late claim. Thứ tự này tránh để một đơn đã hủy nhưng có payment bị phân loại nhầm thành vấn đề giao hàng. Verifier kiểm tra schema, giới hạn số lượng, tính duy nhất và sự tồn tại của entity/evidence ID, tổng tiền, refund, root cause và action trước khi Coordinator ghi file.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_001.json`…`EC_050.json`, policy `EC_POLICY_V1`, ba CSV orders/items/payments |
| Output | Assessment JSON đúng schema trong `output/`, một trace JSONL mỗi case và metadata runtime |
| Module phụ thuộc | Python standard library: `csv`, `json`, `decimal`, `datetime`, `pathlib` |
| Module sử dụng output | Chatbot, frontend và bộ chấm bài |
| Điều kiện lỗi cần xử lý | Thiếu order ID, order không tồn tại, policy sai version, thiếu/sai tên case, ID giả, sai total/refund hoặc case không phân loại được |

### Cách xác minh

```powershell
python -m compileall -q src
python src/main.py --process
cd frontend
npm.cmd ci
npm.cmd run build
```

- **Kết quả mong đợi:** Python compile sạch, xử lý đúng 50 case và frontend build production thành công.
- **Kết quả thực tế:** 50 case đã xử lý; Vite build thành công; kiểm tra độc lập không phát hiện entity ID hoặc total sai.
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/metadata.json`, `output.zip`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Kết luận policy và số tiền cần độ chính xác tuyệt đối, trong khi LLM có thể tạo thông tin không có trong Olist.
- **Các phương án đã cân nhắc:** để một LLM đọc toàn bộ dữ liệu và tự kết luận; hoặc dùng pipeline deterministic cho quyết định, chỉ dùng LLM cho diễn đạt/handoff hội thoại.
- **Phương án đã chọn:** deterministic policy engine là nguồn sự thật; LLM 3B chỉ hỗ trợ giao tiếp và không có quyền sửa assessment.
- **Lý do:** dễ tái lập, chi phí thấp, tuân thủ giới hạn 10B và ngăn hallucination làm thay đổi ID hoặc refund.
- **Bằng chứng:** chạy lại pipeline tạo cùng 50 output; đối soát độc lập cho kết quả không có lỗi ID và financial total.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Verifier ban đầu chỉ kiểm tra prefix và số lượng evidence; một ID đúng định dạng nhưng không tồn tại vẫn có thể vượt qua.
- **Bước tái hiện:** thay `order:<order_id>` bằng `order:not-a-real-order` rồi gọi Verifier.
- **Nguyên nhân gốc:** validation chỉ kiểm tra cấu trúc, chưa so với facts được lấy từ CSV.
- **Cách xử lý:** dựng tập ID hợp lệ từ order/item/payment/seller facts; kiểm tra membership, trùng lặp, evidence bắt buộc, total, refund và policy mapping.
- **Cách xác minh sau khi sửa:** negative test trả `ValueError`; toàn bộ 50 output hợp lệ vẫn chạy qua.
- **Điều học được:** schema validation không thay thế provenance validation; evidence phải vừa đúng định dạng vừa tồn tại trong nguồn.

## 7. Hiểu biết về luồng end-to-end

1. Case cung cấp `claimed_order_id`; Dataset dùng khóa này để lấy order, item/seller và payment rows từ CSV.
2. Các specialist tạo facts theo từng domain và handoff cho Policy Agent; không agent nào tự tạo tracking hay refund event.
3. Policy Agent chọn issue đầu tiên thỏa điều kiện theo thứ tự EC_POLICY_V1, tính responsible party, refund và action.
4. Verifier đối chiếu output với facts nguồn và contract. Chỉ output đạt kiểm tra mới được ghi vào `output/` và trace mới được ghi vào `logging/trace.jsonl`.
5. Chatbot nhận case ID hoặc order ID, gọi lại đúng pipeline này. LLM chỉ chuyển facts đã xác minh thành câu trả lời tiếng Việt; nếu API không khả dụng, hệ thống vẫn trả báo cáo deterministic.

## 8. Cam kết của thành viên

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc thành viên khác.

**Họ và tên:** [Điền họ và tên]

**Ngày xác nhận:** [Điền ngày xác nhận]
