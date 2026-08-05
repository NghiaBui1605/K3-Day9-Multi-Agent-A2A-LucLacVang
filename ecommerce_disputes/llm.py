from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .settings import LLM_API_URL, MODEL_NAME


class LLMError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries without adding a third-party dependency."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


class OpenAILLMClient:
    """Small stdlib client for OpenAI JSON chat completions."""

    def __init__(
        self,
        api_key: str,
        timeout_seconds: int = 60,
        min_interval_seconds: float = 0.2,
    ):
        if not api_key:
            raise LLMError(
                "OPENROUTER_API_KEY (or OPENAI_API_KEY) is empty. Add your key to .env before running the LLM pipeline."
            )
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0

    @classmethod
    def from_env(cls) -> "OpenAILLMClient":
        load_dotenv()
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("GROQ_API_KEY", "")
        )
        return cls(api_key.strip())

    def json_completion(self, system: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": MODEL_NAME,
            "temperature": 0,
            "max_completion_tokens": 256,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))},
            ],
        }
        request = urllib.request.Request(
            LLM_API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "olist-dispute-agents/1.0",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    response_data = json.loads(response.read().decode("utf-8"))
                content = response_data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LLMError("LLM response must be a JSON object")
                return parsed
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")[:500]
                last_error = LLMError(f"OpenAI API HTTP {exc.code}: {error_body}")
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
        raise LLMError(f"LLM request failed after 3 attempts: {last_error}")
