"""
Follow-up question resolution (BUILD SPEC section 18).

Rewrites a short follow-up ("what about Kano?", "compare that with Kaduna")
into a self-contained question using the prior turn's structural context
(table, dimensions, top groups) - never raw row data. The rewritten
question then goes through the exact same generate_sql -> validate ->
execute pipeline as a first-time question; this step only removes the
ambiguity, it does not get any extra trust.
"""
import json
from dataclasses import dataclass
from anthropic import Anthropic
from app.config import settings

_client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

SYSTEM_PROMPT = """You rewrite a short follow-up business question into a
fully self-contained question, using the context of the previous analysis
in this conversation.

Respond ONLY with JSON: {"resolved_question": "..."}

Rules:
- If the new question is already self-contained (doesn't reference "that",
  "it", "what about X" relative to prior context), return it unchanged.
- Only use the prior context to fill in what the question is clearly
  pointing at (e.g. same metric/table, different segment). Never invent
  numbers or claims - you are only resolving pronoun/ellipsis references.
"""


@dataclass
class ResolvedQuestion:
    resolved_question: str


def resolve(question: str, context: dict) -> ResolvedQuestion:
    if not context or _client is None:
        return ResolvedQuestion(resolved_question=question)

    payload = {"previous_analysis_context": context, "new_question": question}
    resp = _client.messages.create(
        model=settings.llm_model_fast,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    text_out = "".join(b.text for b in resp.content if b.type == "text").strip()
    text_out = text_out.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text_out)
        return ResolvedQuestion(resolved_question=parsed.get("resolved_question", question))
    except json.JSONDecodeError:
        return ResolvedQuestion(resolved_question=question)


def build_context_snapshot(question: str, table: str | None, value_col: str | None,
                            group_col: str | None, date_col: str | None,
                            by_group: list[dict] | None) -> dict:
    """Only structural facts and small aggregates - safe to replay into a
    prompt, never raw records."""
    return {
        "last_question": question,
        "table": table,
        "value_col": value_col,
        "group_col": group_col,
        "date_col": date_col,
        "top_groups": (by_group or [])[:5],
    }
