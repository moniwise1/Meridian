"""Operator-selected inference, with no automatic cross-provider data fallback.

The adapter preserves the existing bounded, validated analytics tool loop.
It does not give models HTTP, filesystem, shell, or credential access.
"""
import json
import math
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from anthropic import Anthropic

from app.config import settings


class ModelProviderError(RuntimeError):
    pass


def validate_model_config(s):
    if s.llm_provider not in {"anthropic", "ollama"}:
        raise ModelProviderError("LLM_PROVIDER must be anthropic or ollama.")
    if not math.isfinite(s.llm_timeout_seconds) or not 1 <= s.llm_timeout_seconds <= 600:
        raise ModelProviderError("LLM_TIMEOUT_SECONDS must be between 1 and 600.")
    if not 1024 <= s.llm_max_response_bytes <= 8_000_000:
        raise ModelProviderError("LLM_MAX_RESPONSE_BYTES is outside the supported range.")
    if s.llm_provider != "ollama":
        return
    url = urlsplit(s.ollama_base_url)
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"} or url.scheme not in {"http", "https"}):
        raise ModelProviderError("OLLAMA_BASE_URL must be an origin without credentials or query parameters.")
    try:
        url.port
    except ValueError:
        raise ModelProviderError("OLLAMA_BASE_URL has an invalid port.") from None
    private = url.hostname in {"localhost", "127.0.0.1", "::1"} or url.hostname.endswith(".railway.internal")
    if url.scheme == "http" and not private:
        raise ModelProviderError("Remote inference requires HTTPS; HTTP is limited to loopback or Railway private networking.")
    if not s.ollama_model_fast.strip() or not s.ollama_model_reasoning.strip():
        raise ModelProviderError("Configure both OLLAMA_MODEL_FAST and OLLAMA_MODEL_REASONING before selecting ollama.")


def _block_dict(block):
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return vars(block)


def _messages(system, messages, vision):
    if isinstance(system, list):
        system = "\n".join(b.get("text", "") for b in system)
    converted = [{"role": "system", "content": system}]
    tool_names = {}
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
            continue
        text, images, calls, results = [], [], [], []
        for original in content:
            b = _block_dict(original)
            kind = b.get("type")
            if kind == "text":
                text.append(b["text"])
            elif kind == "image" and vision:
                source = b["source"]
                if source.get("type") != "base64":
                    raise ModelProviderError("Only embedded images are supported.")
                images.append(source["data"])
            elif kind == "tool_use":
                tool_names[b["id"]] = b["name"]
                calls.append({"function": {"name": b["name"], "arguments": b["input"]}})
            elif kind == "tool_result":
                if b["tool_use_id"] not in tool_names:
                    raise ModelProviderError("Tool result has no matching request.")
                results.append({"role": "tool", "content": b["content"],
                                "tool_name": tool_names[b["tool_use_id"]]})
            else:
                raise ModelProviderError("Unsupported inference content block.")
        if text or images or calls:
            item = {"role": message["role"], "content": "\n".join(text)}
            if images:
                item["images"] = images
            if calls:
                item["tool_calls"] = calls
            converted.append(item)
        converted.extend(results)
    return converted


class OllamaClient:
    def __init__(self, s, vision=False, transport=None):
        validate_model_config(s)
        self.s, self.vision, self.transport = s, vision, transport
        self.messages = self

    def create(self, *, model, max_tokens, system, messages, tools=None, thinking=None):
        selected = (self.s.ollama_model_vision if self.vision else
                    self.s.ollama_model_fast if model == self.s.llm_model_fast else
                    self.s.ollama_model_reasoning)
        if not selected:
            raise ModelProviderError("A vision model is not configured.")
        payload = {"model": selected, "stream": False, "think": False,
                   "messages": _messages(system, messages, self.vision),
                   "options": {"num_predict": min(max_tokens, 16000), "temperature": 0}}
        allowed = {t["name"] for t in tools or []}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]
            }} for t in tools]
        try:
            # No ambient proxies, cookies, redirect forwarding, or provider failover.
            with httpx.Client(timeout=self.s.llm_timeout_seconds, trust_env=False,
                              follow_redirects=False, transport=self.transport) as client:
                with client.stream("POST", self.s.ollama_base_url.rstrip("/") + "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > self.s.llm_max_response_bytes:
                            raise ModelProviderError("Inference response exceeded its size limit.")
            data = json.loads(raw)
        except (httpx.HTTPError, ValueError):
            # Provider error bodies may echo private prompts. Never surface them.
            raise ModelProviderError("The configured inference service could not complete this request.") from None
        if not isinstance(data, dict) or data.get("done") is not True:
            raise ModelProviderError("Inference returned an incomplete response.")
        msg = data.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content", ""), str):
            raise ModelProviderError("Inference returned an invalid message.")
        if data.get("done_reason") == "length":
            raise ModelProviderError("Inference reached its output limit; shorten the request.")
        blocks = []
        if msg.get("content"):
            blocks.append(SimpleNamespace(type="text", text=msg["content"]))
        calls = msg.get("tool_calls", [])
        if not isinstance(calls, list) or len(calls) > 16:
            raise ModelProviderError("Inference returned an invalid tool batch.")
        for call in calls:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            if function.get("name") not in allowed or not isinstance(function.get("arguments"), dict):
                raise ModelProviderError("Inference requested an unauthorized or invalid tool.")
            blocks.append(SimpleNamespace(type="tool_use", id=str(uuid.uuid4()),
                                          name=function["name"], input=function["arguments"]))
        if not blocks:
            raise ModelProviderError("Inference returned no usable content.")
        return SimpleNamespace(content=blocks, stop_reason="tool_use" if calls else "end_turn",
                               usage=SimpleNamespace(output_tokens=data.get("eval_count", 0)))


def get_model_client(*, vision=False):
    validate_model_config(settings)
    if settings.llm_provider == "ollama":
        if vision and not settings.ollama_model_vision:
            return None
        return OllamaClient(settings, vision=vision)
    if not settings.anthropic_api_key:
        return None
    return Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds,
                     max_retries=1)
