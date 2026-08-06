# BÁO CÁO CÁ NHÂN — DAY 9: MULTI-AGENT A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Trần Huy Hoàng |
| Mã học viên | 01709 |
| Khóa/Lớp | K3 |
| Vai trò chính | Xây dựng pipeline xử lý tranh chấp, tích hợp OpenRouter Multi-Agent, Verifier và artifact nộp bài |
| Ngày hoàn thành | 2026-08-05 |

## 2. Bài toán nghiệp vụ

Hệ thống xử lý 50 khiếu nại thương mại điện tử từ `input/EC_001.json` đến `input/EC_050.json`. Mỗi khiếu nại chỉ chứa thông tin khách hàng cung cấp nên không thể được coi ngay là sự thật. Hệ thống phải đối chiếu mã đơn với dữ liệu nguồn Olist, xác định đúng vấn đề chính, bên chịu trách nhiệm, bằng chứng, số tiền và hành động xử lý.

Sáu nhóm nghiệp vụ theo `EC_POLICY_V1` gồm:

1. Đơn đã hủy nhưng đã thanh toán.
2. Đơn không khả dụng nhưng đã thanh toán.
3. Giao trễ do người bán bàn giao hàng sau hạn.
4. Giao trễ do khâu logistics.
5. Thanh toán tách hợp lệ.
6. Khiếu nại giao trễ không được dữ liệu nguồn hỗ trợ.

Kết quả mỗi case phải nhất quán trên sáu nhóm tiêu chí: đánh giá case, entity liên quan, nguyên nhân gốc, bằng chứng, tài chính và hành động xử lý. Đầu ra cuối cùng là đúng 50 file JSON trong thư mục `output/`, đồng thời phải đóng gói thành `output.zip` với đường dẫn nội bộ `output/EC_001.json` đến `output/EC_050.json`.

## 3. Vai trò và phần việc của tôi

Tôi phụ trách luồng xử lý từ dữ liệu nguồn đến kết quả đã xác minh, đồng thời hoàn thiện cơ chế gọi agent thật qua OpenRouter. Các phần việc chính thể hiện trực tiếp trong lịch sử nhánh `tranhuyhoang`:

| Phần việc | File/Artifact | Kết quả |
| --- | --- | --- |
| Xử lý bộ 50 case chính thức | `src/dispute_pipeline.py`, `input/`, `output/` | Sinh đủ 50 kết quả từ cùng một pipeline, không viết riêng đáp án cho từng case |
| Tạo và kiểm tra gói nộp | `output.zip` | Giữ đúng thư mục `output/` bên trong ZIP |
| Chuẩn hóa bằng chứng thanh toán | `src/dispute_pipeline.py` | Sắp xếp payment ID theo thứ tự số trước khi giới hạn danh sách |
| Đồng bộ confidence với kết quả đã kiểm chứng | `src/dispute_pipeline.py` | Confidence phản ánh kết luận deterministic đã qua Verifier |
| Chạy agent thật qua OpenRouter | `src/chatbot.py`, `src/llm_multi_agent.py`, `src/main.py` | Dùng `qwen/qwen3-8b`, năm lượt gọi agent cho mỗi case |
| Chọn evidence theo chính sách nghiệp vụ | `src/dispute_pipeline.py` | Chỉ giữ bằng chứng chứng minh trực tiếp điều kiện policy hoặc phương án tài chính |
| Bổ sung kiểm thử hồi quy | `tests/test_dispute_pipeline.py` | Kiểm tra đủ 50 case, evidence giả, thứ tự payment, độ liên quan evidence và contract OpenRouter |

Các commit tiêu biểu của tôi gồm `ac34aaa`, `6835d0e`, `7f6f01a`, `e0514ff`, `f9f1eed` và `3a59903`.

## 4. Kiến trúc giải pháp

```text
Case JSON + CSV Olist
        |
        v
Order & Seller Agent ----+
Payment Agent -----------+--> Policy Agent --> Canonical Assessment
Delivery Agent ----------+                         |
                                                   v
                                              Verifier Agent
                                                   |
                           +-----------------------+--------------------+
                           |                                            |
                           v                                            v
                  output/EC_xxx.json                     OpenRouter specialists
                  trace + metadata                      + Coordinator response
```

Kiến trúc gồm hai lớp bổ trợ nhau:

- **Lớp deterministic** đọc dữ liệu CSV, tính toán và áp dụng `EC_POLICY_V1`. Đây là nguồn sự thật cho issue, entity, root cause, refund và action. Cùng một dữ liệu đầu vào luôn tạo cùng một kết quả.
- **Lớp OpenRouter Multi-Agent** dùng `qwen/qwen3-8b` (8.2B tham số, đáp ứng giới hạn không quá 10B). Các specialist nhận facts đã giới hạn theo domain và bàn giao kết quả cho Coordinator. LLM dùng để tổng hợp và giải thích, không được sửa kết luận canonical hay số tiền hoàn.

Theo `logging/metadata.json`, chế độ chạy hiện tại là `openrouter_multi_agent`, xử lý 50 case và thực hiện năm lượt gọi LLM cho mỗi case. Khi OpenRouter không khả dụng, báo cáo deterministic đã qua Verifier vẫn là kết quả có thể sử dụng; lỗi mạng không được phép làm thay đổi nghiệp vụ.

## 5. Luồng hoạt động end-to-end

1. `src/main.py` đọc từng case, kiểm tra tên case, phiên bản policy và `claimed_order_id`.
2. `Dataset.load` nạp các bảng order, item và payment; `collect_facts` nối dữ liệu theo `order_id`.
3. `order_and_seller_agent` lấy trạng thái đơn, item và seller có liên quan.
4. `payment_agent` dùng `Decimal` để tính tổng giá hàng, phí vận chuyển và tiền đã thanh toán, tránh sai số số thực.
5. `delivery_agent` so sánh ngày giao thực tế với ngày dự kiến, đồng thời so sánh thời điểm carrier nhận hàng với `shipping_limit_date` của từng seller.
6. `policy_agent` xét sáu policy theo thứ tự ưu tiên. Thứ tự này ngăn một đơn đã hủy nhưng có payment bị phân loại nhầm thành vấn đề giao hàng.
7. `build_assessment` tạo issue, entity, root cause, evidence, financial resolution và action.
8. `verifier_agent` kiểm tra schema, giới hạn số lượng, ID tồn tại trong dữ liệu nguồn, evidence không trùng, policy mapping, tổng tiền và refund.
9. Chỉ kết quả vượt qua Verifier mới được ghi vào `output/`; trace và metadata được ghi vào `logging/` để kiểm toán.
10. Ở chế độ `--llm-agents`, facts đã xác minh được chuyển qua các OpenRouter specialist và Coordinator để tạo phần giải thích có handoff rõ ràng.

## 6. Các quyết định nghiệp vụ quan trọng

### 6.1. Không coi lời khiếu nại là dữ liệu sự thật

Nội dung khách hàng chỉ giúp xác định đơn cần tra cứu. Trạng thái đơn, mốc giao hàng, payment và số tiền đều phải lấy từ CSV. Cách này tránh hallucination và không cho phép một lời mô tả thiếu chính xác làm thay đổi refund.

### 6.2. Phân biệt entity liên quan và evidence chứng minh

Một entity có quan hệ với đơn hàng chưa chắc là bằng chứng phù hợp cho kết luận. Tôi điều chỉnh lựa chọn evidence theo policy:

- Mọi case luôn có `order:<id>` và `policy:<cause_code>`.
- Case hủy hoặc không khả dụng sau thanh toán dùng payment evidence; item không chứng minh được trạng thái hủy/không khả dụng nên bị loại.
- Seller evidence chỉ xuất hiện khi seller là bên chịu trách nhiệm.
- Case giao trễ do seller chỉ chọn item thực sự vi phạm `shipping_limit_date`.
- Case split payment ưu tiên các payment row để chứng minh tổng tiền được chia thành nhiều giao dịch hợp lệ.

Đây là thay đổi trực tiếp nhắm vào chất lượng nghiệp vụ của tiêu chí “Bằng chứng”, thay vì tăng số lượng ID một cách cơ học.

### 6.3. Xử lý tài chính có thể tái lập

Tất cả số tiền được tính bằng `Decimal` và làm tròn theo cent. Payment ID được chuẩn hóa theo phần số trước khi chọn evidence, vì thứ tự đọc CSV không phải là một quy tắc nghiệp vụ. Refund phụ thuộc issue: hoàn tổng tiền cho đơn hủy/không khả dụng, hoàn phí vận chuyển cho lỗi giao trễ phù hợp, và không tự tạo refund cho split payment hợp lệ hoặc khiếu nại không được hỗ trợ.

### 6.4. Kết hợp LLM và deterministic agent

Nếu chỉ dùng LLM, câu trả lời linh hoạt nhưng có nguy cơ tạo sai ID, nguyên nhân hoặc số tiền. Nếu chỉ dùng deterministic pipeline, kết quả chính xác nhưng phần hội thoại và giải thích kém tự nhiên. Vì vậy tôi chọn kiến trúc lai: agent LLM chịu trách nhiệm phân tích theo vai trò và diễn đạt; deterministic policy cùng Verifier giữ quyền quyết định cuối cùng.

## 7. Lỗi đã xử lý và bài học

### Evidence hợp lệ về định dạng nhưng không liên quan nghiệp vụ

- **Triệu chứng:** evidence có thể tồn tại trong dữ liệu nguồn nhưng không trực tiếp chứng minh policy đang áp dụng, làm tiêu chí bằng chứng thấp hơn các tiêu chí khác.
- **Nguyên nhân:** logic cũ lấy nhiều entity theo một mẫu chung cho mọi issue.
- **Cách sửa:** xây danh sách evidence riêng theo từng nhóm policy và thêm rule trong Verifier để từ chối seller evidence ở case không do seller, cũng như item evidence ở case hủy/không khả dụng.
- **Kiểm thử:** `test_evidence_is_relevant_to_the_selected_business_policy` duyệt toàn bộ 50 input và kiểm tra các ràng buộc này.
- **Bài học:** provenance chỉ trả lời “ID có thật hay không”; relevance mới trả lời “ID có chứng minh kết luận hay không”. Cả hai đều cần thiết.

### Cấu trúc ZIP không đúng contract nộp bài

- **Triệu chứng:** file JSON đầy đủ nhưng công cụ chấm không tìm thấy đúng đường dẫn yêu cầu.
- **Nguyên nhân:** ZIP từng chỉ chứa JSON ở thư mục gốc.
- **Cách sửa:** đóng gói và xác minh để archive giữ tiền tố `output/`.
- **Bài học:** artifact contract là một phần của hệ thống, không chỉ là bước đóng gói sau cùng.

## 8. Kiểm thử và cách tái hiện

Các lệnh dùng để kiểm tra:

```powershell
python -m compileall -q src
python -m unittest discover -s tests -v
python src/main.py --process --llm-agents --workers 4
python -m zipfile -l output.zip
```

Điều kiện đạt:

- Toàn bộ unit test vượt qua, bao gồm test chạy 50 case và test Verifier từ chối evidence giả.
- Có đúng `output/EC_001.json` đến `output/EC_050.json`.
- Mỗi output chỉ tham chiếu entity/evidence tồn tại và phù hợp với policy.
- `logging/metadata.json` ghi đúng model `qwen/qwen3-8b`, kích thước 8.2B, 50 case và năm lượt LLM/case.
- `output.zip` chứa đúng 50 JSON dưới thư mục `output/`, không chứa secret hoặc file thừa.

## 9. Tự đánh giá

Phần đóng góp quan trọng nhất của tôi không phải là tạo thủ công 50 đáp án, mà là xây một quy trình tổng quát có thể giải thích và kiểm chứng. Pipeline tách rõ facts, policy, verification và presentation nên có thể sửa một quy tắc rồi chạy lại toàn bộ dữ liệu. Tôi cũng hiểu rằng điểm cao ở bài toán này không chỉ đến từ phân loại đúng: evidence phải thật sự liên quan, số tiền phải có quy tắc rõ ràng, action phải phù hợp với responsible party và artifact nộp bài phải đúng contract.

Giới hạn hiện tại là chất lượng phần diễn giải vẫn phụ thuộc model và dịch vụ OpenRouter. Tuy nhiên, giới hạn này không làm thay đổi kết luận nghiệp vụ vì mọi trường quan trọng đều bị khóa bởi canonical assessment và Verifier.

## 10. Cam kết

- [x] Báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Các kết quả được nêu đều có thể đối chiếu bằng source code, test, output hoặc metadata trong repository.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Nội dung được viết theo phần đóng góp của tôi, không tham chiếu hoặc sao chép báo cáo cá nhân của thành viên khác.

**Họ và tên:** Trần Huy Hoàng

**Ngày xác nhận:** 2026-08-05
