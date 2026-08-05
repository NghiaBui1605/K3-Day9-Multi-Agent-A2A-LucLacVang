"""Local Vietnamese web chatbot for the Olist dispute-resolution pipeline.

Run: python src/chatbot.py
Then browse to http://127.0.0.1:8000.  The chatbot is intentionally grounded:
it accepts a real 32-character Olist order ID or an available EC case ID and
uses the deterministic policy pipeline to answer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from config import DEFAULT_OPENROUTER_MODEL, OPENROUTER_CHAT_COMPLETIONS_URL
from dispute_pipeline import Dataset, POLICY_VERSION, process_case
from llm_multi_agent import LLMOrchestrator


ROOT = Path(__file__).resolve().parents[1]
ORDER_ID_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
CASE_ID_RE = re.compile(r"\bEC_\d{3}\b", re.IGNORECASE)

ISSUE_TEXT = {
    "canceled_order_paid": "Đơn đã bị hủy sau khi phát sinh thanh toán.",
    "unavailable_order_paid": "Đơn không còn khả dụng sau khi phát sinh thanh toán.",
    "late_delivery_seller": "Đơn giao trễ và seller đã bàn giao cho carrier quá hạn.",
    "late_delivery_logistics": "Đơn giao trễ nhưng seller bàn giao đúng hạn; trách nhiệm thuộc logistics.",
    "valid_split_payment": "Các khoản thanh toán tách nhỏ được đối soát hợp lệ.",
    "unsupported_late_claim": "Dữ liệu cho thấy đơn được giao không trễ hơn ngày dự kiến.",
}
CAUSE_TEXT = {
    "SELLER_HANDOFF_AFTER_LIMIT": "Seller bàn giao cho đơn vị vận chuyển sau shipping limit.",
    "CARRIER_DELIVERED_AFTER_ESTIMATE": "Carrier giao cho khách sau ngày giao dự kiến.",
    "ORDER_CANCELED_AFTER_PAYMENT": "Đơn đã hủy nhưng có thanh toán.",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT": "Đơn không khả dụng nhưng có thanh toán.",
    "MULTIPLE_PAYMENTS_RECONCILED": "Nhiều payment row khớp với item và freight.",
    "DELIVERY_WITHIN_ESTIMATE": "Ngày giao cho khách không vượt ngày dự kiến.",
}

SYSTEM_PROMPT = """Bạn là trợ lý chăm sóc khách hàng Olist, trả lời bằng tiếng Việt.
Bạn sẽ nhận được một yêu cầu khách hàng và, khi có mã đơn hợp lệ, một BÁO CÁO
ĐÃ XÁC MINH do hệ thống chính sách tạo. Chỉ dùng các chi tiết trong báo cáo đó;
không tạo thêm tracking, refund, sự kiện giao hàng hay số tiền. Không được thay
đổi primary_issue, số tiền hoàn, action, bên chịu trách nhiệm hoặc evidence IDs.
Nếu không có báo cáo, hãy lịch sự yêu cầu mã case EC_### hoặc order_id Olist gồm
32 ký tự hex. Trả lời ngắn gọn, rõ ràng, không quá 250 từ."""


def load_dotenv(path: Path) -> None:
    """Load only missing values from a minimal local .env file, without deps."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


class OpenRouterClient:
    """Small stdlib-only client for OpenRouter's OpenAI-compatible chat API."""

    def __init__(self, api_key: str, model: str = DEFAULT_OPENROUTER_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def complete(self, messages: list[dict[str, str]], max_tokens: int = 450) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        request = Request(
            OPENROUTER_CHAT_COMPLETIONS_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://127.0.0.1",
                "X-OpenRouter-Title": "Olist Dispute Assistant",
            },
        )
        try:
            with urlopen(request, timeout=45) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code == 404 and "unavailable for free" in detail.lower():
                raise FreeModelUnavailableError from error
            raise OpenRouterServiceError(f"HTTP {error.code}") from error
        except URLError as error:
            raise OpenRouterServiceError("network unavailable") from error
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise OpenRouterServiceError("invalid completion payload") from error
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterServiceError("empty completion")
        return content.strip()

    def chat(self, user_message: str, report: str | None, history: list[dict[str, str]]) -> str:
        safe_history = [
            {"role": entry["role"], "content": entry["content"][:2_000]}
            for entry in history[-6:]
            if entry.get("role") in {"user", "assistant"} and isinstance(entry.get("content"), str)
        ]
        context = "Không có báo cáo đơn hàng cho lượt này."
        if report:
            context = "BÁO CÁO ĐÃ XÁC MINH (nguồn sự thật):\n" + report
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *safe_history]
        messages.append({
            "role": "user",
            "content": f"Yêu cầu hiện tại: {user_message}\n\n{context}",
        })
        return self.complete(messages)


class OpenRouterServiceError(RuntimeError):
    """An upstream failure whose internal details must not be shown to customers."""


class FreeModelUnavailableError(OpenRouterServiceError):
    """OpenRouter retired the configured :free model variant."""


class DisputeChatbot:
    """A narrow chatbot adapter: natural-language input -> verified assessment."""

    def __init__(self, data_dir: Path, input_dir: Path, api_key: str | None = None) -> None:
        self.dataset = Dataset.load(data_dir)
        self.input_dir = input_dir
        self.client = OpenRouterClient(api_key) if api_key else None
        self.orchestrator = LLMOrchestrator(self.client, self.dataset) if self.client else None

    def reply(self, message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        message = message.strip()
        if not message:
            return {
                "reply": "Bạn hãy gửi mã đơn Olist hoặc mã case, ví dụ `EC_001`.",
                "missing_fields": ["claimed_order_id"],
                "conversation_state": {"phase": "missing_order_identifier"},
            }

        case = self._find_case(message)
        if case is None:
            order_match = ORDER_ID_RE.search(message)
            if not order_match:
                return {
                    "reply": "Mình có thể kiểm tra khiếu nại này. Bạn gửi mã case như EC_001 hoặc mã đơn Olist gồm 32 ký tự để mình đối chiếu dữ liệu nhé.",
                    "missing_fields": ["claimed_order_id"],
                    "conversation_state": {"phase": "missing_order_identifier"},
                    "model_used": None,
                }
            case = self._case_for_order(order_match.group(0).lower())

        try:
            result, trace = process_case(self.dataset, case)
        except ValueError as error:
            return {"reply": f"Không thể xác minh yêu cầu này: {error}"}
        verified_report = self._explain(result)
        if self.orchestrator:
            try:
                orchestration = self.orchestrator.run(message, case, result, history or [])
                trace["llm_handoffs"] = orchestration.handoffs
                return {
                    "reply": orchestration.reply + f"\n\n---\nKết quả xác minh từ hệ thống:\n{verified_report}",
                    "assessment": result,
                    "trace": trace,
                    "model_used": self.client.model,
                    "conversation_state": {
                        "phase": "resolved",
                        "case_id": case["case_id"],
                        "claimed_order_id": case["customer_request"]["claimed_order_id"],
                    },
                }
            except FreeModelUnavailableError:
                return {
                    "reply": "Model miễn phí tạm không còn khả dụng. Hệ thống vẫn đã kiểm tra trực tiếp từ dữ liệu Olist và đưa kết quả xác minh bên dưới.\n\n" + verified_report,
                    "assessment": result,
                    "trace": trace,
                    "model_used": None,
                    "conversation_state": {
                        "phase": "resolved",
                        "case_id": case["case_id"],
                        "claimed_order_id": case["customer_request"]["claimed_order_id"],
                    },
                }
            except OpenRouterServiceError:
                return {
                    "reply": "Trợ lý ngôn ngữ đang tạm không phản hồi. Hệ thống vẫn đã hoàn tất kiểm tra bằng policy engine.\n\n" + verified_report,
                    "assessment": result,
                    "trace": trace,
                    "model_used": self.client.model,
                    "conversation_state": {
                        "phase": "resolved",
                        "case_id": case["case_id"],
                        "claimed_order_id": case["customer_request"]["claimed_order_id"],
                    },
                }
        response = self._model_reply(message, verified_report, result, history or [])
        response["trace"] = trace
        response["conversation_state"] = {
            "phase": "resolved",
            "case_id": case["case_id"],
            "claimed_order_id": case["customer_request"]["claimed_order_id"],
        }
        return response

    def _model_reply(
        self,
        message: str,
        report: str | None,
        assessment: dict[str, Any] | None,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        if self.client is None:
            setup = "Chưa cấu hình OpenRouter. Hãy copy `.env.example` thành `.env` và đặt `OPENROUTER_API_KEY`."
            reply = f"{setup}\n\n{report}" if report else setup
            return {"reply": reply, "assessment": assessment, "model_used": None}
        try:
            reply = self.client.chat(message, report, history)
            # The model improves the conversational wording only.  Always
            # expose the exact deterministic report as the authoritative
            # resolution so a model wording error cannot alter a decision.
            if report:
                reply += f"\n\n---\nKết quả xác minh từ hệ thống:\n{report}"
            return {"reply": reply, "assessment": assessment, "model_used": self.client.model}
        except FreeModelUnavailableError:
            fallback = report or "Bạn hãy gửi mã case EC_### hoặc mã đơn Olist để mình kiểm tra."
            return {
                "reply": "Model miễn phí tạm không còn khả dụng. " + fallback,
                "assessment": assessment,
                "model_used": None,
            }
        except OpenRouterServiceError:
            fallback = report or "Hãy gửi mã case EC_### hoặc order ID Olist để kiểm tra."
            return {
                "reply": "Trợ lý ngôn ngữ đang tạm không phản hồi.\n\nBáo cáo xác minh cục bộ:\n" + fallback,
                "assessment": assessment,
                "model_used": self.client.model,
            }

    def _find_case(self, message: str) -> dict[str, Any] | None:
        match = CASE_ID_RE.search(message)
        if not match:
            return None
        filename = f"{match.group(0).upper()}.json"
        path = self.input_dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _case_for_order(order_id: str) -> dict[str, Any]:
        return {
            "case_id": f"CHAT_{order_id[:8]}",
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Khách hàng yêu cầu kiểm tra đơn qua chatbot.",
                "claimed_order_id": order_id,
            },
            "policy_version": POLICY_VERSION,
        }

    @staticmethod
    def _explain(result: dict[str, Any]) -> str:
        assessment = result["assessment"]
        financial = result["financial_resolution"]
        entities = result["affected_entities"]
        cause = result["root_cause_analysis"]["ranked_causes"][0]["cause_code"]
        parties = result["root_cause_analysis"]["responsible_parties"]
        party_text = "Không xác định bên cần chịu trách nhiệm hoàn tiền."
        if parties:
            party_text = "Bên chịu trách nhiệm: " + ", ".join(
                f"{party['party_type']} ({party['party_id']})" for party in parties
            ) + "."
        refund = financial["recommended_refund_brl"]
        return "\n".join([
            f"Đã kiểm tra đơn `{entities['order_ids'][0]}`.",
            f"Kết luận: **{assessment['primary_issue']}** — {ISSUE_TEXT[assessment['primary_issue']]}",
            f"Nguyên nhân: {CAUSE_TEXT[cause]}",
            party_text,
            (
                "Đối soát tiền: item {item:.2f} BRL, freight {freight:.2f} BRL, "
                "payment {payment:.2f} BRL."
            ).format(
                item=financial["item_total_brl"],
                freight=financial["freight_total_brl"],
                payment=financial["payment_total_brl"],
            ),
            f"Đề xuất: hoàn **{refund:.2f} BRL**; hành động `{result['resolution_actions'][0]}`.",
            "Bằng chứng: " + ", ".join(f"`{evidence}`" for evidence in result["evidence_ids"]),
        ])


PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Olist Dispute Assistant</title><style>
*{box-sizing:border-box}body{margin:0;background:#f6f7fb;color:#172033;font:16px system-ui,sans-serif}
main{max-width:850px;margin:0 auto;padding:32px 16px}h1{margin:0 0 5px}p{color:#596579}.chat{height:62vh;overflow:auto;padding:10px 0}.bubble{white-space:pre-wrap;line-height:1.55;max-width:88%;padding:14px 16px;border-radius:16px;margin:10px 0}.bot{background:#fff;border:1px solid #e1e5ee}.user{background:#214bd7;color:#fff;margin-left:auto}form{display:flex;gap:10px;background:#fff;padding:12px;border:1px solid #e1e5ee;border-radius:16px}input{flex:1;border:0;font:inherit;outline:none;padding:8px}button{border:0;border-radius:10px;background:#214bd7;color:white;font:inherit;padding:10px 17px;cursor:pointer}small{color:#68748a}</style></head>
<body><main><h1>Olist Dispute Assistant</h1><p>Trợ lý kiểm tra khiếu nại dựa trên dữ liệu Olist và EC_POLICY_V1.</p>
<section id="chat" class="chat"><div class="bubble bot">Chào bạn. Gửi mã case (ví dụ EC_001) hoặc mã đơn Olist để mình kiểm tra.</div></section>
<form id="form"><input id="message" autocomplete="off" placeholder="Ví dụ: Kiểm tra EC_001" autofocus><button>Gửi</button></form>
<p><small>Chatbot chỉ kết luận từ bản ghi CSV, không suy diễn sự kiện ngoài dữ liệu.</small></p>
</main><script>
const chat=document.querySelector('#chat'), form=document.querySelector('#form'), input=document.querySelector('#message'), history=[];
function add(text, type){const box=document.createElement('div');box.className='bubble '+type;box.textContent=text;chat.append(box);chat.scrollTop=chat.scrollHeight;}
form.addEventListener('submit',async e=>{e.preventDefault();const message=input.value.trim();if(!message)return;const prior=history.slice(-8);add(message,'user');history.push({role:'user',content:message});input.value='';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,history:prior})});const data=await r.json();add(data.reply,'bot');history.push({role:'assistant',content:data.reply})}catch(_){add('Không kết nối được với chatbot.','bot')}});
</script></body></html>"""


def make_handler(bot: DisputeChatbot) -> type[BaseHTTPRequestHandler]:
    class ChatHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send(HTTPStatus.OK, PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 20_000:
                    raise ValueError("Tin nhắn quá dài.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                raw_history = payload.get("history", [])
                history = raw_history if isinstance(raw_history, list) else []
                response = bot.reply(str(payload.get("message", "")), history)
                body = json.dumps(response, ensure_ascii=False).encode("utf-8")
                self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")
            except (json.JSONDecodeError, ValueError) as error:
                body = json.dumps({"reply": f"Yêu cầu không hợp lệ: {error}"}, ensure_ascii=False).encode("utf-8")
                self._send(HTTPStatus.BAD_REQUEST, body, "application/json; charset=utf-8")
            except Exception:
                # Never let a provider or model-format failure close a chat
                # request without a JSON response for the frontend.
                body = json.dumps({
                    "reply": "Dịch vụ xử lý tạm thời gặp lỗi. Vui lòng thử lại sau.",
                }, ensure_ascii=False).encode("utf-8")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, body, "application/json; charset=utf-8")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", self._cors_origin())
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", self._cors_origin())
            self.end_headers()
            self.wfile.write(body)

        def _cors_origin(self) -> str:
            origin = self.headers.get("Origin", "")
            return origin if origin in {"http://localhost:5173", "http://127.0.0.1:5173"} else "http://127.0.0.1:5173"

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ChatHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Olist dispute chatbot")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    chatbot = DisputeChatbot(ROOT / "data", ROOT / "input", api_key)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(chatbot))
    print(f"Chatbot running at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nChatbot stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
