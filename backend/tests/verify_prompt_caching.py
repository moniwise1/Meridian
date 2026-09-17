"""
Verification for prompt caching (cache_control) on the Anthropic call sites.

Caching fails SILENTLY when it's wrong: a misplaced breakpoint, a prompt
that drifts below the model's minimum cacheable length, or a system prompt
that stops being byte-identical between calls all produce a perfectly good
answer at full price. Nothing raises, nothing logs, the bill just goes back
up. That is exactly the class of regression a test has to hold.

Uses the same fake Anthropic client style as
verify_document_analysis_v2.py - no live API key, no network.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_prompt_caching.py
"""
import base64
import copy
import json
import os
import tempfile
from types import SimpleNamespace

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"

from app.agents import insight_agent
from app.agents import query_generator
from app.agents.insight_agent import _CACHE_CONTROL, _CACHED_SYSTEM_MIN_CHARS


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, input_):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id="toolu_fake1")


def _response(blocks):
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=blocks, stop_reason=stop,
                           usage=SimpleNamespace(output_tokens=42))


class _FakeMessages:
    def __init__(self, turns):
        self._turns, self._n, self.calls = turns, 0, []

    def create(self, **kwargs):
        # DEEP copy, not a reference. explain_document_only_v2 appends to
        # the same `messages` list across loop iterations, so storing the
        # kwargs as handed over would leave every captured call pointing at
        # one final mutated list - and "the cached prefix didn't change
        # between iterations" would then be trivially, uselessly true.
        self.calls.append(copy.deepcopy(kwargs))
        blocks = self._turns[min(self._n, len(self._turns) - 1)]
        self._n += 1
        return _response(blocks)


def _install(turns):
    client = SimpleNamespace(messages=_FakeMessages(turns))
    insight_agent._client = client
    return client.messages


_ANSWER = json.dumps({"what": "Example finding.", "confidence": "medium",
                      "confidence_explanation": "", "data_quality_caveat": "",
                      "next_question": "", "where": "", "when": "", "contributors": ""})


def _breakpoints(kwargs):
    """Every cache_control marker in one .create() call, as
    ("system"|"message", index) pairs."""
    found = []
    system = kwargs.get("system")
    if isinstance(system, list):
        found += [("system", i) for i, b in enumerate(system) if b.get("cache_control")]
    for mi, message in enumerate(kwargs.get("messages") or []):
        content = message.get("content")
        if isinstance(content, list):
            found += [("message", mi) for b in content
                      if isinstance(b, dict) and b.get("cache_control")]
    return found


# --- 1. the database path marks its system prompt -------------------------
messages = _install([[_text_block(_ANSWER)]])
insight_agent.explain("What was revenue?", {"total": 10}, [])
system = messages.calls[0]["system"]
assert isinstance(system, list), "system must be a block list for cache_control to attach"
assert system[-1]["cache_control"] == _CACHE_CONTROL, system[-1]
assert _breakpoints(messages.calls[0]) == [("system", 0)], _breakpoints(messages.calls[0])
print("1. OK  explain() sends its system prompt as a cache-marked block")


# --- 2. the same prompt is byte-identical across different questions ------
#        (a prefix that varies per call can never be read back)
messages = _install([[_text_block(_ANSWER)]])
insight_agent.explain("A completely different question?", {"total": 999}, ["a note"])
assert messages.calls[0]["system"] == system, "the cached prefix changed between two calls"
print("2. OK  the cached prefix is identical for two different questions")


# --- 3. it is long enough to actually be cacheable ------------------------
#        (Sonnet's minimum is 1024 tokens; below it the breakpoint is
#         ignored silently and this whole change stops paying for itself)
for name, block in [("explain", system[0])]:
    assert len(block["text"]) >= _CACHED_SYSTEM_MIN_CHARS, (
        f"{name}'s system prompt is {len(block['text'])} chars, below the "
        f"~{_CACHED_SYSTEM_MIN_CHARS} needed to clear Sonnet's 1024-token minimum")
print(f"3. OK  the system prompt clears the minimum cacheable length ({len(system[0]['text'])} chars)")


# --- 4. the document path caches BOTH the system prompt and the document --
#        and the tool loop re-reads them instead of re-sending them
messages = _install([
    [_tool_block("render_chart", {"chart_type": "bar", "title": "T",
                                  "labels": ["A", "B"], "values": [1, 2]})],
    [_text_block(json.dumps({"what": "Example.", "confidence": "medium"}))],
])
insight_agent.explain_document_only_v2(
    "Summarise this.", [{"filename": "big.pdf", "kind": "pdf", "text": "x" * 40_000}])
assert len(messages.calls) == 2, f"expected a two-turn tool loop, got {len(messages.calls)}"

first, second = messages.calls
assert set(_breakpoints(first)) == {("system", 0), ("message", 0)}, _breakpoints(first)
assert len(first["system"][0]["text"]) >= _CACHED_SYSTEM_MIN_CHARS
document_block = first["messages"][0]["content"][0]
assert document_block["cache_control"] == _CACHE_CONTROL
assert len(document_block["text"]) > 30_000, "the document text should be the bulk of this prefix"
print("4. OK  the document path marks both its system prompt and the document text")


# --- 5. the cached prefix survives the tool loop unchanged ----------------
#        Everything the loop appends must land AFTER the breakpoint, or the
#        second call re-pays for the document instead of reading it back.
assert second["system"] == first["system"], "the system prefix changed between loop iterations"
assert second["messages"][0] == first["messages"][0], (
    "the cached first message changed between loop iterations - the second "
    "call would miss and re-pay for the whole document")
assert len(second["messages"]) > len(first["messages"]), "the loop appended nothing"
assert set(_breakpoints(second)) == {("system", 0), ("message", 0)}, _breakpoints(second)
print("5. OK  the tool loop appends after the breakpoints, so iteration 2 is a cache hit")


# --- 6. tools sit in front of system, so one breakpoint covers both -------
#        Anthropic builds the cacheable prefix as tools -> system ->
#        messages, which is the only reason a separate tools breakpoint
#        isn't needed. If tools ever stopped being sent this assumption
#        would need revisiting.
assert first.get("tools"), "the v2 call should still be sending tool schemas"
assert not any("cache_control" in t for t in first["tools"]), (
    "a tools breakpoint is redundant - the system breakpoint already covers them")
print("6. OK  tools are covered by the system breakpoint, not marked separately")


# --- 7. the Haiku call site is deliberately NOT cached --------------------
#        Haiku's minimum cacheable prefix is 2048 tokens and this prompt is
#        about half that, so a breakpoint would be silently ignored. This
#        asserts the deliberate omission so nobody "fixes" it later and
#        assumes a saving that isn't happening.
query_generator._client = SimpleNamespace(messages=_FakeMessages(
    [[_text_block(json.dumps({"sql": "SELECT 1", "rationale": "r"}))]]))
query_generator.generate_sql("Revenue?", "TABLE t(a INT)")
sql_call = query_generator._client.messages.calls[0]
assert isinstance(sql_call["system"], str), (
    "query_generator's system prompt is below Haiku's 2048-token minimum; a "
    "cache_control here buys nothing - see the comment at that call site")
assert _breakpoints(sql_call) == [], _breakpoints(sql_call)
print("7. OK  the Haiku SQL call is deliberately uncached (below its minimum)")


# --- 8. at most 4 breakpoints per call (the API's hard limit) -------------
for i, call in enumerate(messages.calls):
    assert len(_breakpoints(call)) <= 4, f"call {i} has {len(_breakpoints(call))} breakpoints, max is 4"
print("8. OK  no call exceeds the 4-breakpoint limit")

print("\nALL PROMPT CACHING CHECKS PASSED")
