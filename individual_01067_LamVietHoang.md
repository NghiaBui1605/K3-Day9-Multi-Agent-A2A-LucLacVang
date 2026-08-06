# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung |
| --------------- | -------- |
| Họ và tên       | Lâm Việt Hoàng |
| MSSV            | 2A202601067 |
| Khóa/Lớp        | K3 |
| Vai trò chính   | Backend / Policy pipeline engineer |
| Ngày hoàn thành | 2026-08-06 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | ----------------- | ---------- |
| Xây dựng logic phân loại dispute policy | src/dispute_pipeline.py (collect_facts, classify, build_assessment, verifier_agent, process_case) | Case JSON đầu vào và dữ liệu Olist từ thư mục data/ | Assessment JSON, evidence IDs, financial_resolution, trace log | Hoàn thành |
| Tạo batch output và artifact cho 50 case | src/main.py và thư mục output/ | Các file input EC_*.json | 50 file JSON output, logging/trace.jsonl, logging/metadata.json | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Tích hợp với chatbot và cấu hình runtime | src/chatbot.py, src/config.py | Pipeline có thể được gọi từ giao diện chatbot local và giữ model/config rõ ràng hơn |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Triển khai pipeline quyết định chính sách theo EC_POLICY_V1 | src/dispute_pipeline.py | Mỗi case được gán primary_issue, responsible party, refund và evidence IDs dựa trên dữ liệu CSV | Chạy pipeline và kiểm tra các file JSON trong output/ |
| Thêm cơ chế fallback cho case lỗi để batch không bị dừng | src/dispute_pipeline.py | Ngay cả khi case có lỗi, hệ thống vẫn sinh output schema-valid thay vì crash toàn bộ batch | Chạy lệnh xử lý và đối chiếu log trace |
| Tạo và kiểm chứng 50 output case | output/EC_001.json đến output/EC_050.json | Tất cả 50 case được tạo thành công với metadata/log phù hợp | Chạy lệnh python src/main.py --process |

Output cụ thể mà tôi tạo ra và xác minh: các file output/EC_001.json đến output/EC_050.json cùng với logging/trace.jsonl và logging/metadata.json.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Tôi cần làm cho hệ thống multi-agent dispute resolution có thể chuyển dữ liệu từ case JSON và dữ liệu Olist thành một kết quả có thể kiểm chứng, nhất quán và không bị dừng bởi một case lỗi duy nhất.

### Cách triển khai

Tôi thiết kế pipeline theo hướng deterministic: mỗi case được đọc từ input JSON, ánh xạ tới order_id được claim, sau đó lấy facts từ các bảng orders/items/payments, phân tích delivery lateness và reconciliation payment. Từ các facts này, hệ thống áp dụng quy tắc ưu tiên EC_POLICY_V1 để chọn primary issue, responsible party, refund và action. Ngoài ra, tôi thêm verifier để kiểm tra giới hạn schema và evidence IDs trước khi ghi output. Nếu một case gặp lỗi như policy version không hợp lệ hoặc order_id không tồn tại, hệ thống sẽ dùng fallback schema-valid thay vì làm batch dừng lại.

### Input, output và contract

| Thành phần | Mô tả |
| ---------- | ----- |
| Input | Case JSON từ input/EC_*.json và dữ liệu CSV trong data/ |
| Output | JSON assessment theo schema chuẩn với assessment, affected_entities, root_cause_analysis, evidence_ids, financial_resolution, resolution_actions |
| Module phụ thuộc | src/dispute_pipeline.py, src/main.py |
| Module sử dụng output | output/ và logging/ |
| Điều kiện lỗi cần xử lý | Order ID không tồn tại, policy_version sai, dữ liệu thiếu hoặc case không phân loại được |

### Cách xác minh

```bash
python src/main.py --process
```

- **Kết quả mong đợi:** Tạo đầy đủ 50 file output và ghi trace/metadata.
- **Kết quả thực tế:** Terminal trả về “Processed 50 cases.”
- **Artifact/log:** output/, logging/trace.jsonl, logging/metadata.json

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần chọn giữa một pipeline hoàn toàn dựa trên LLM hoặc một pipeline deterministic dựa trên dữ liệu thực tế.
- **Các phương án đã cân nhắc:**
  - Dùng prompt/LLM để tự suy luận toàn bộ quyết định.
  - Dùng engine quy tắc + verifier để suy luận từ dữ liệu CSV.
- **Phương án đã chọn:** Dùng deterministic rule-based pipeline có fallback.
- **Lý do:** Độ chính xác và khả năng tái lặp tốt hơn, tránh việc model “tạo” thông tin không có trong dữ liệu và giúp batch chạy ổn định.
- **Bằng chứng quyết định phù hợp:** Kết quả chạy pipeline thành công cho 50 case và sinh artifact đầy đủ.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Một case lỗi có thể làm toàn bộ batch dừng lại hoặc không tạo được output.
- **Lệnh hoặc bước tái hiện:** Chạy pipeline với case không hợp lệ hoặc order_id không tồn tại.
- **Nguyên nhân gốc:** Luồng xử lý trước đây ném exception trực tiếp, không có bước fallback để giữ batch tiếp tục chạy.
- **Cách xử lý:** Thêm fallback_result và bọc process_case trong try/except trong process_directory.
- **Cách xác minh sau khi sửa:** Chạy lại python src/main.py --process; kết quả là 50 cases vẫn được xử lý và ghi output.
- **Điều học được:** Khi xây dựng pipeline tự động, nên ưu tiên một kết quả bảo toàn schema và conservative hơn là để một lỗi nhỏ làm toàn bộ run fail.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của mình:

1. Trong repo này, dữ liệu không đi qua Crossref hoặc vector index. Dữ liệu bắt đầu từ file input JSON và các CSV Olist trong thư mục data/, sau đó được load vào Dataset, rồi các agent/func phân tích order, payment và delivery để tạo facts.
2. Không có evaluation set riêng như một benchmark retrieval; thay vào đó, 50 case đầu vào được xử lý bằng cùng một chính sách EC_POLICY_V1 và kết quả được so sánh với dữ liệu thật từ CSV để đảm bảo quyết định hợp lệ.
3. Quality checks xảy ra ở hai tầng: verifier kiểm tra schema và giới hạn ID, còn trace/metadata ghi lại flow và kết quả chạy cho mỗi case.
4. Vì mục tiêu là tính nhất quán, tất cả case đều chạy qua cùng một engine chính sách, thay vì dùng nhiều cách xử lý khác nhau cho cùng một tập dữ liệu.
5. Một run được xem là thành công khi tất cả 50 JSON output được tạo, có schema đúng và có log/metadata đầy đủ; đây là artifact và metric chính trong bài lab này.

**Câu trả lời:**

Pipeline bắt đầu từ input case, đọc dữ liệu nguồn từ CSV Olist, dựng facts về đơn hàng, thanh toán và giao hàng, sau đó áp dụng quy tắc chính sách để tạo assessment và ghi output. Mỗi output được verifier kiểm tra trước khi lưu; nếu một case lỗi thì hệ thống vẫn tạo một kết quả an toàn và kế tục xử lý các case còn lại.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Lâm Việt Hoàng
**Ngày xác nhận:** 2026-08-06
