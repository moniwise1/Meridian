"""
Query Generator (BUILD SPEC section 10 & 20).

Calls the LLM to translate a natural-language question + policy-filtered
schema into ONE read-only SQL query. The schema text is the only "instruction
surface" the model sees here — it is built entirely from our own trusted
schema description, never from unstructured content the model retrieved
elsewhere (see agents/planner.py for how retrieved data is kept separate
from instructions, per section 20's prompt-injection defence).

The model's output is treated as untrusted and MUST pass
security.query_validator before it is ever executed.
"""
import json
from dataclasses import dataclass
from anthropic import Anthropic
from app.config import settings

_client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

SYSTEM_PROMPT = """You are a SQL generation component inside a secure analytics system.
You will be given a database schema (already filtered to only the tables and
columns this user is authorized to see) and a business question.

Rules:
- Output ONLY valid JSON: {"sql": "...", "rationale": "..."}
- The SQL must be a single read-only SELECT (or WITH ... SELECT) statement.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, MERGE, or any DDL/DML.
- Never reference a table or column that is not explicitly listed in the schema you were given.
- Prefer aggregation (GROUP BY, SUM, AVG, COUNT) over returning raw rows whenever the
  question can be answered that way — the goal is the smallest result set that answers
  the question, not a full table dump.
- If the question cannot be answered with the given schema, return {"sql": "", "rationale": "explain why"}.
"""


@dataclass
class GeneratedQuery:
    sql: str
    rationale: str


def generate_sql(question: str, schema_text: str) -> GeneratedQuery:
    if _client is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    user_prompt = f"Schema (authorized tables/columns only):\n{schema_text}\n\nQuestion: {question}"

    resp = _client.messages.create(
        model=settings.llm_model_fast,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text_out = "".join(b.text for b in resp.content if b.type == "text").strip()
    text_out = text_out.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(text_out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Query generator returned non-JSON output: {e}") from e

    return GeneratedQuery(sql=parsed.get("sql", ""), rationale=parsed.get("rationale", ""))
