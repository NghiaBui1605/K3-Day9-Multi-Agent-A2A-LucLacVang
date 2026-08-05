"""
LLM Client – shared OpenRouter/OpenAI-compatible client.
Model: qwen/qwen-2.5-7b-instruct (7B params, <= 10B requirement)
API key is loaded from .env (not hardcoded, not committed).
"""

import os
import json
import logging
from pathlib import Path
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load .env manually (no python-dotenv needed)
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Model name is declared in source code (not in .env) per submission rules
MODEL_NAME = "qwen/qwen-2.5-7b-instruct"
BASE_URL = "https://openrouter.ai/api/v1"


def get_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set in .env")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> str:
    """
    Call the LLM and return the text response.
    temperature=0 for deterministic, reproducible outputs.
    """
    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = resp.choices[0].message.content or ""
        logger.debug(f"[LLM] tokens={resp.usage.total_tokens if resp.usage else 'N/A'}")
        return content.strip()
    except Exception as e:
        logger.error(f"[LLM] Call failed: {e}")
        raise


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> dict:
    """
    Call the LLM and parse JSON response.
    Returns empty dict on parse failure.
    """
    raw = call_llm(system_prompt, user_prompt, max_tokens, temperature)
    # Extract JSON block if wrapped in markdown
    if "```" in raw:
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"[LLM] JSON parse failed. Raw: {raw[:200]}")
        return {}
