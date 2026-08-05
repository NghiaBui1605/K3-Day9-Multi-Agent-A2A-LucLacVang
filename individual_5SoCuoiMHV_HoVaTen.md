# Báo cáo cá nhân - Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Bùi Hữu Nghĩa |
| MSSV | 2A202601880 |
| Khóa/Lớp | K3 |
| Vai trò chính | Thiết kế và triển khai pipeline multi-agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

Phần việc sở hữu gồm repository đọc CSV theo order, các agent điều tra order/seller, payment, delivery và policy, coordinator điều phối handoff, verifier kiểm tra schema/evidence/financial, trace chạy thật và gói output nộp bài.

| Module/deliverable | File phụ trách | Input | Output | Trạng thái |
| --- | --- | --- | --- | --- |
| Data và domain contract | `repository.py`, `models.py` | Olist CSV, order ID | Typed findings, `Decimal` totals | Hoàn thành |
| Multi-agent orchestration | `agents.py`, `coordinator.py` | Case và domain findings | Verified decision | Hoàn thành |
| Validation và artifact | `verifier.py`, `runner.py`, `verify_outputs.py` | Decision và row thật | 50 JSON, trace, metadata, zip | Hoàn thành |
| Kiểm thử | `tests/test_policy.py` | Synthetic findings | Kiểm tra 6 nhánh và priority | Hoàn thành |

## 3. Kết quả theo vai trò

- Pipeline xử lý đủ 50 case và tạo đúng `EC_001.json` đến `EC_050.json`.
- Trace có 300 event, tương ứng 6 event nhận/handoff/xác minh trên mỗi case.
- `output.zip` có đúng 50 entry `output/EC_001.json` đến `output/EC_050.json`, không có source, log hoặc file lạ.
- Phân bố kết quả: 8 canceled paid, 8 unavailable paid, 8 seller late, 8 logistics late, 9 valid split payment và 9 unsupported late claim.
- Validator tái tính kết quả từ CSV và kiểm tra toàn bộ JSON đã lưu.

Lệnh xác minh:

```bash
python run_pipeline.py
python verify_outputs.py
python -m unittest discover -v
```

## 4. Giải thích kỹ thuật

### Vấn đề cần giải quyết

Một claim giao trễ không đủ để kết luận trách nhiệm. Pipeline phải join order với item, seller và payment; phân biệt seller giao carrier muộn với carrier giao khách muộn; đồng thời ưu tiên trạng thái canceled/unavailable đã thanh toán trước các dấu hiệu delivery.

### Cách triển khai

Coordinator gửi cùng order ID cho các agent domain. Order & Seller Agent xác định item và seller có `order_delivered_carrier_date > shipping_limit_date`. Payment Agent cộng riêng price, freight và từng payment row bằng `Decimal`, sau đó đối soát trong sai số 0.10 BRL. Delivery Agent so sánh ngày giao khách với estimated date. Policy Agent áp dụng đúng thứ tự sáu rule. Verifier dựng ID chỉ từ row tồn tại, kiểm giới hạn set/schema, mapping action và số tiền trước khi cho ghi file.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `EC_*.json`, ba CSV policy-relevant và seller master |
| Output | JSON đúng schema README, trace JSONL, metadata JSON, zip 50 case |
| Module phụ thuộc | `models`, `repository`, `settings` |
| Module dùng output | Coordinator, verifier, runner |
| Điều kiện lỗi | Thiếu input/order, sai policy, evidence giả, mismatch tiền, không khớp rule |

## 5. Quyết định kỹ thuật quan trọng

- Bối cảnh: bài toán có policy tường minh, cần số tiền và evidence chính xác tuyệt đối.
- Phương án cân nhắc: dùng LLM cho từng agent; hoặc agent xác định với typed handoff và rule engine.
- Phương án chọn: agent xác định chạy local, model 0 tham số.
- Lý do: tái lập, không tốn API, không lộ secret, không hallucinate ID và nằm dưới giới hạn 10B.
- Bằng chứng: hai lần chạy có cùng 50 output nghiệp vụ; verifier độc lập pass toàn bộ file và unit test cover sáu nhánh.

## 6. Lỗi/blocker đã xử lý

- Triệu chứng: order `unavailable` không có item row nhưng vẫn có payment.
- Nguyên nhân gốc: dữ liệu Olist không đảm bảo mọi order đều có row trong order items.
- Cách xử lý: repository trả tuple rỗng, Payment Agent đặt item/freight total bằng `0.00`, entity item/seller rỗng; policy hoàn đủ payment theo nhánh ưu tiên.
- Cách xác minh: các case unavailable tạo đúng payment evidence, không tạo item/seller evidence giả và được `verify_outputs.py` chấp nhận.
- Bài học: không dùng row giả hoặc suy diễn dữ liệu để lấp join bị thiếu.

## 7. Hiểu biết luồng end-to-end

Case input cung cấp order ID. Repository nạp duy nhất dữ liệu liên quan và trao view read-only cho agent. Các agent domain tạo finding độc lập; Policy Agent chỉ quyết định từ finding; Verifier quay lại tập row thật để kiểm entity, evidence và tài chính. Coordinator ghi output và trace khi mọi gate đã pass. Batch runner kiểm đúng 50 tên file rồi tạo zip từ whitelist cố định, do đó artifact nộp không thể vô tình chứa source hay audit log.

## 8. Cam kết tự kiểm tra

- [x] Nội dung phản ánh đúng phần việc và mức hiểu kỹ thuật.
- [x] Có thể giải thích luồng end-to-end và contract giữa các agent.
- [x] Chỉ ghi kết quả đã được chạy và kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Họ tên và MSSV đã được chủ repo cập nhật trước khi nộp.
