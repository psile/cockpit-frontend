"""Cockpit LLM Proxy — local sidecar for the cockpit frontend.

Borrows Mem0 OSS proxy pattern (mem0.proxy.main.Completions.create):
  search memories → format into prompt → LLM completion → return reply

Config comes from .env in the same directory — no manual env vars needed.
"""

from __future__ import annotations

import os
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


# ── Mem0 OSS MEMORY_ANSWER_PROMPT (adapted for cockpit) ────────────────────

COCKPIT_ANSWER_PROMPT = """\
你是一个车载智能语音助手。根据用户提供的历史记忆和当前对话，生成自然、简洁的回复。

规则：
- 从历史记忆中提取与当前问题相关的信息
- 如果记忆中有相关偏好，自然地在回复中体现（如"您之前说喜欢..."），但不要生硬
- 如果没有相关记忆，正常回答用户问题，不要说"未找到记忆"
- 回复控制在 1-2 句话，口语化，适合语音播报
"""

# ── Defaults (point to company server vLLM) ──
DEFAULT_LLM_MODEL = "memory-llm"
DEFAULT_LLM_BASE_URL = "http://10.133.72.161:20140/v1"
DEFAULT_PROXY_PORT = "8767"


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


@app.post("/chat")
async def chat(req: ChatProxyRequest) -> dict:
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    llm_base_url = os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)

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
    url = f"{llm_base_url}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm_model,
                    "messages": prepared,
                    "temperature": 0.7,
                    "max_tokens": 500,
                    "top_p": 0.8,
                },
            )
    except httpx.ConnectTimeout:
        return {"reply": "(连接超时：无法连接服务器模型服务，请检查网络或服务器状态)", "model": llm_model, "error": "connect_timeout"}
    except httpx.ConnectError as e:
        return {"reply": "(连接被拒绝：服务器模型服务可能未启动，请检查 10.133.72.161:20140)", "model": llm_model, "error": "connect_refused"}
    except httpx.RequestError as e:
        return {"reply": f"(网络请求异常: {e})", "model": llm_model, "error": "network_error"}

    # ── Error: HTTP non-2xx ──
    if not resp.is_success:
        # API Key invalid → 401/403; server error → 5xx
        hint = ""
        if resp.status_code in (401, 403):
            hint = "（API Key 可能不正确或与服务器 vLLM 不一致，请检查 .env 中 LLM_API_KEY）"
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
        reply = choices[0]["message"]["content"]
    except (KeyError, TypeError, IndexError):
        return {"reply": "(服务器响应格式异常，无法提取回复内容)", "model": llm_model, "error": "malformed_response"}

    return {"reply": reply, "model": llm_model}


@app.get("/health")
async def health() -> dict:
    api_key = os.getenv("LLM_API_KEY", "")
    return {
        "status": "ok" if api_key else "no_api_key",
        "model": os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        "base_url": os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        "api_key": _mask_key(api_key),
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
    print(f"  Model:   {os.getenv('LLM_MODEL', DEFAULT_LLM_MODEL)}")
    print(f"  Base URL: {os.getenv('LLM_BASE_URL', DEFAULT_LLM_BASE_URL)}")
    print(f"  API Key: {'configured (' + _mask_key(api_key) + ')' if api_key else 'NOT SET — edit .env'}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
