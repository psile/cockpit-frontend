"""Cockpit LLM Proxy — local sidecar for the cockpit frontend.

Borrows Mem0 OSS proxy pattern (mem0.proxy.main.Completions.create):
  search memories → format into prompt → LLM completion → return reply

Config comes from .env in the same directory — no manual env vars needed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Load .env from the same directory as this script
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# ── Qwen3 thinking tag constants ──
# Built from chr codes to avoid XML parsing issues in tooling
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"
_THINK_OPEN_PATTERN = re.compile(_THINK_OPEN, re.IGNORECASE)
_THINK_FULL_PATTERN = re.compile(_THINK_OPEN + r".*?" + _THINK_CLOSE, re.DOTALL | re.IGNORECASE)


# ── Cockpit answer prompt (concise, no thinking output) ───────────────────

COCKPIT_ANSWER_PROMPT = """\
你是一个简洁、自然的车载智能语音助手。
请结合相关历史记忆和用户当前问题，直接给出最终回答。
必须遵守：
- 只输出最终回答
- 禁止输出分析、推理、思考过程、回答计划或规则说明
- 回答控制在1至2句话
- 一般不超过50个汉字
- 用户只是打招呼时，只需简短回应
- 不复述用户问题
- 不解释你如何检索或使用记忆
- 不要输出"首先""接下来""按照规则""我需要回应"等分析性内容
- 有相关偏好时自然体现，不要刻意强调"根据历史记忆"
- 没有相关记忆时正常回答，不要说"未找到记忆"
- 使用自然、简短、适合车载语音播报的中文
"""

# ── Defaults (point to company server vLLM) ──
DEFAULT_LLM_MODEL = "memory-llm"
DEFAULT_LLM_BASE_URL = "http://10.133.72.161:20140/v1"
DEFAULT_PROXY_PORT = "8767"
DEFAULT_ENABLE_THINKING = False
DEFAULT_MAX_TOKENS = 128
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOP_P = 0.8


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


class ChatProxyRequest(BaseModel):
    messages: list[dict]
    memory_context: list[str] | None = None


app = FastAPI(title="Cockpit LLM Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mask_key(key: str) -> str:
    """Mask API key for safe logging — show only first/last 4 chars."""
    if not key or len(key) <= 12:
        return "***" if key else "(empty)"
    return key[:4] + "..." + key[-4:]


def _strip_thinking(reply: str) -> str:
    """Remove Qwen3 thinking blocks if they leak through.

    Handles both closed and unclosed thinking tags.
    """
    # Remove closed thinking blocks
    reply = _THINK_FULL_PATTERN.sub("", reply).strip()
    # Handle unclosed tag — remove from opening tag to end
    if _THINK_OPEN_PATTERN.search(reply):
        idx = _THINK_OPEN_PATTERN.search(reply).start()
        reply = reply[:idx].strip()
    return reply


@app.post("/chat")
async def chat(req: ChatProxyRequest) -> dict:
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    llm_base_url = os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    enable_thinking = _get_bool("LLM_ENABLE_THINKING", DEFAULT_ENABLE_THINKING)
    max_tokens = _get_int("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)
    temperature = _get_float("LLM_TEMPERATURE", DEFAULT_TEMPERATURE)
    top_p = _get_float("LLM_TOP_P", DEFAULT_TOP_P)

    # ── Error: API Key not configured ──
    if not llm_api_key:
        return {
            "reply": "(LLM_API_KEY 未配置，请在 .env 中设置与服务器 vLLM 一致的 API Key)",
            "model": llm_model,
            "error": "api_key_missing",
        }

    # Step 1: prepend system prompt (Mem0 pattern: _prepare_messages)
    prepared = [{"role": "system", "content": COCKPIT_ANSWER_PROMPT}]
    for msg in req.messages:
        if msg.get("role") != "system":
            prepared.append(msg)

    # Step 2: format memories into the last user message (Mem0 pattern: _format_query_with_memories)
    if req.memory_context and prepared and prepared[-1]["role"] == "user":
        memories_text = "\n".join(f"- {m}" for m in req.memory_context)
        user_question = prepared[-1]["content"]
        prepared[-1]["content"] = (
            f"- 相关历史记忆:\n{memories_text}\n\n"
            f"- 用户当前问题: {user_question}"
        )
    elif req.memory_context:
        memories_text = "\n".join(f"- {m}" for m in req.memory_context)
        prepared.append({"role": "user", "content": f"- 相关历史记忆:\n{memories_text}"})

    # Step 3: call LLM (OpenAI-compatible endpoint on company server)
    # NOTE: chat_template_kwargs.enable_thinking is for Qwen3-32B.
    # If switching to Qwen3.8 or other models, verify thinking control compatibility.
    url = f"{llm_base_url}/chat/completions"
    request_body = {
        "model": llm_model,
        "messages": prepared,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        # Qwen3-32B: disable thinking mode via chat_template_kwargs
        "chat_template_kwargs": {
            "enable_thinking": enable_thinking,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
    except httpx.ConnectTimeout:
        return {"reply": "(连接超时：无法连接服务器模型服务，请检查网络或服务器状态)", "model": llm_model, "error": "connect_timeout"}
    except httpx.ConnectError:
        return {"reply": "(连接被拒绝：服务器模型服务可能未启动，请检查 10.133.72.161:20140)", "model": llm_model, "error": "connect_refused"}
    except httpx.RequestError as e:
        return {"reply": f"(网络请求异常: {e})", "model": llm_model, "error": "network_error"}

    # ── Error: HTTP non-2xx ──
    if not resp.is_success:
        hint = ""
        if resp.status_code in (401, 403):
            hint = "（API Key 可能不正确或与服务器 vLLM 不一致，请检查 .env 中 LLM_API_KEY）"
        elif resp.status_code == 400:
            hint = "（请求参数被拒绝，请检查 chat_template_kwargs.enable_thinking 是否被服务器支持）"
        elif resp.status_code >= 500:
            hint = "（服务器模型服务内部错误，请检查 vLLM 状态）"
        try:
            err_body = resp.text[:300]
        except Exception:
            err_body = ""
        return {
            "reply": f"(HTTP {resp.status_code}: {hint}{err_body})",
            "model": llm_model,
            "error": f"http_{resp.status_code}",
        }

    # ── Error: invalid JSON ──
    try:
        data = resp.json()
    except Exception:
        return {"reply": "(服务器返回了非 JSON 响应，可能模型服务异常)", "model": llm_model, "error": "invalid_json"}

    # ── Error: missing choices ──
    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        return {"reply": "(服务器响应缺少 choices，模型可能未正常生成)", "model": llm_model, "error": "missing_choices"}

    try:
        reply = choices[0]["message"].get("content") or ""
    except (KeyError, TypeError, IndexError):
        return {"reply": "(服务器响应格式异常，无法提取回复内容)", "model": llm_model, "error": "malformed_response"}

    # ── Strip thinking tags (fallback if enable_thinking not honored) ──
    reply = _strip_thinking(reply)

    # ── Error: empty reply after cleanup ──
    if not reply or not reply.strip():
        return {"reply": "模型未返回有效回答", "model": llm_model, "error": "empty_reply"}

    return {"reply": reply.strip(), "model": llm_model}


@app.get("/health")
async def health() -> dict:
    api_key = os.getenv("LLM_API_KEY", "")
    return {
        "status": "ok" if api_key else "no_api_key",
        "model": os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        "base_url": os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        "api_key": _mask_key(api_key),
        "enable_thinking": _get_bool("LLM_ENABLE_THINKING", DEFAULT_ENABLE_THINKING),
        "max_tokens": _get_int("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cockpit LLM Proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PROXY_PORT", DEFAULT_PROXY_PORT)))
    args = parser.parse_args()

    import uvicorn

    api_key = os.getenv("LLM_API_KEY", "")
    print(f"LLM Proxy starting on http://{args.host}:{args.port}")
    print(f"  Model:           {os.getenv('LLM_MODEL', DEFAULT_LLM_MODEL)}")
    print(f"  Base URL:        {os.getenv('LLM_BASE_URL', DEFAULT_LLM_BASE_URL)}")
    print(f"  Enable thinking: {_get_bool('LLM_ENABLE_THINKING', DEFAULT_ENABLE_THINKING)}")
    print(f"  Max tokens:      {_get_int('LLM_MAX_TOKENS', DEFAULT_MAX_TOKENS)}")
    print(f"  Temperature:     {_get_float('LLM_TEMPERATURE', DEFAULT_TEMPERATURE)}")
    print(f"  API Key:         {'configured (' + _mask_key(api_key) + ')' if api_key else 'NOT SET — edit .env'}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
