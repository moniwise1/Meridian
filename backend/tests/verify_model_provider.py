"""Inference transport contract and fail-closed security, with no paid calls."""
import os
os.environ["APP_SECRET_KEY"] = "test-provider-key"
os.environ["ANTHROPIC_API_KEY"] = ""
import json
from types import SimpleNamespace
import httpx
from app.config import Settings
from app.agents.model_provider import OllamaClient, ModelProviderError, validate_model_config

s = Settings(llm_provider="ollama", ollama_model_fast="local-fast",
             ollama_model_reasoning="local-reasoning")
tool = {"name": "compute_aggregate", "description": "Calculate bounded values",
        "input_schema": {"type": "object"}}
requests = []
def handler(request):
    payload = json.loads(request.content)
    requests.append(payload)
    if len(requests) == 1:
        assert payload["model"] == "local-reasoning"
        assert payload["stream"] is False and payload["think"] is False
        assert payload["tools"][0]["function"]["name"] == "compute_aggregate"
        return httpx.Response(200, json={"done": True, "message": {"content": "", "tool_calls": [
            {"function": {"name": "compute_aggregate", "arguments": {"values": [2, 3]}}}]}})
    assert payload["messages"][-1] == {"role": "tool", "content": "5", "tool_name": "compute_aggregate"}
    assert payload["messages"][-2]["tool_calls"][0]["function"]["arguments"] == {"values": [2, 3]}
    return httpx.Response(200, json={"done": True, "message": {"content": '{"what":"Total is 5"}'}})

client = OllamaClient(s, transport=httpx.MockTransport(handler))
messages = [{"role": "user", "content": [{"type": "text", "text": "Calculate", "cache_control": {"type": "ephemeral"}}]}]
first = client.messages.create(model=s.llm_model_reasoning, max_tokens=100, system=[{"text": "Rules"}], messages=messages, tools=[tool])
assert first.stop_reason == "tool_use"
messages += [{"role": "assistant", "content": first.content}, {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": first.content[0].id, "content": "5"}]}]
second = client.messages.create(model=s.llm_model_reasoning, max_tokens=100, system="Rules", messages=messages, tools=[tool])
assert second.stop_reason == "end_turn" and "Total is 5" in second.content[0].text

def rejected(response, *, limit=2_000_000):
    local = s.model_copy(update={"llm_max_response_bytes": limit})
    c = OllamaClient(local, transport=httpx.MockTransport(lambda request: response))
    try:
        c.create(model=s.llm_model_fast, max_tokens=100, system="Rules", messages=[{"role":"user", "content":"private"}], tools=[tool])
    except ModelProviderError as exc:
        assert "private" not in str(exc)
        return
    raise AssertionError("unsafe response accepted")

rejected(httpx.Response(302, headers={"location": "https://attacker.example"}))
rejected(httpx.Response(500, text="private prompts and secrets"))
rejected(httpx.Response(200, content=b"x" * 2048), limit=1024)
rejected(httpx.Response(200, json={"done":False,"message":{"content":"partial"}}))
rejected(httpx.Response(200, json={"done":True,"done_reason":"length","message":{"content":"truncated"}}))
rejected(httpx.Response(200, json={"done":True,"message":{"content":"","tool_calls":[{"function":{"name":"shell","arguments":{}}}]}}))
rejected(httpx.Response(200, json={"done":True,"message":{"content":"","tool_calls":[{"function":{"name":"compute_aggregate","arguments":"bad"}}]}}))
for updates in [{"ollama_base_url":"http://public.example"}, {"ollama_base_url":"https://user:secret@model.example"},
                {"ollama_base_url":"https://model.example/?secret=x"}, {"ollama_model_fast":""},
                {"llm_provider":"unknown"}, {"llm_timeout_seconds":float("nan")}]:
    try:
        validate_model_config(s.model_copy(update=updates))
    except ModelProviderError:
        continue
    raise AssertionError(updates)
for origin in ["http://model.railway.internal:11434", "https://model.example"]:
    validate_model_config(s.model_copy(update={"ollama_base_url":origin}))
print("Provider tool roundtrip, transport limits, sanitized errors and configuration guards passed")
