# Hướng dẫn chạy và kiểm tra

Yêu cầu Python 3.10 trở lên và OpenAI API key. Model thật được cố định trong source là `gpt-4o-mini`; không đặt model name trong `.env`. OpenAI không công bố số tham số nên cấu hình này không chứng minh được giới hạn ≤10B của đề.

Điền key vào `.env`:

```dotenv
OPENAI_API_KEY=sk-...
```

Không gửi hoặc commit file này. `.gitignore` đã loại trừ `.env`.

```bash
python run_pipeline.py
python verify_outputs.py
python -m unittest discover -v
```

`run_pipeline.py` yêu cầu đúng 50 file `input/EC_001.json` đến `input/EC_050.json`. Mỗi lượt chạy sẽ:

1. Nạp các row Olist liên quan từ `data/`.
2. Chạy các agent và chỉ ghi output sau khi verifier pass.
3. Thay lượt trace cũ bằng lượt mới tại `logging/trace.jsonl`.
4. Cập nhật `logging/metadata.json`.
5. Tạo `output.zip` chứa đúng `output/EC_001.json` đến `output/EC_050.json` và không chứa source/log.

`verify_outputs.py` tái tính độc lập toàn bộ quyết định, financial fields, affected entities và evidence IDs rồi so sánh với 50 file đã lưu.

## Các lệnh tùy chọn

```bash
python run_pipeline.py --input input --data data --output output --logging logging --zip output.zip
python run_pipeline.py --no-llm  # chỉ dùng để chẩn đoán offline, không dùng cho lượt nộp
python -m compileall -q ecommerce_disputes run_pipeline.py verify_outputs.py
```

Nếu thiếu API key/input/order, sai policy, API lỗi, model trả sai rule hoặc case không khớp nhánh policy nào, pipeline dừng với lỗi thay vì tạo output suy diễn.
