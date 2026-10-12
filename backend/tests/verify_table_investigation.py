"""Known-answer file investigation and a realistic model/tool roundtrip."""
import os
os.environ["APP_SECRET_KEY"] = "test-table-investigation"
os.environ["ANTHROPIC_API_KEY"] = ""
import json
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from app.agents.table_tools import ParsedTable, TableWorkspace
from app.agents import insight_agent

frame = pd.DataFrame({"store": ["Eket", "Eket", "Uyo", "Uyo"],
                      "wait": [10.0, 30.0, 5.0, None], "sold": [2, 3, 4, 1]})
w = TableWorkspace([ParsedTable("table-1", "september.csv", frame),
                    ParsedTable("table-2", "october.csv", pd.DataFrame({"store":["Eket"], "wait":[8.0]}))])
r = w.execute({"table_id":"table-1", "operation":"average", "value_column":"wait", "group_column":"store"})
assert r["result"] == 15 and r["groups"] == [{"group":"Eket", "value":20.0, "row_count":2}, {"group":"Uyo", "value":5.0, "row_count":2}]
assert r["excluded_numeric_values"] == 1
r = w.execute({"table_id":"table-1", "operation":"sum", "value_column":"sold", "filters":[{"column":"store", "operator":"eq", "value":"Eket"}]})
assert r["result"] == 5 and r["matched_row_count"] == 2
assert w.execute({"table_id":"table-2", "operation":"average", "value_column":"wait"})["result"] == 8
assert w.execute({"table_id":"table-1", "operation":"count", "filters":[{"column":"wait", "operator":"gt", "value":15}]})["result"] == 1
r = w.execute({"table_id":"table-1", "operation":"sum", "value_column":"sold", "filters":[{"column":"store", "operator":"eq", "value":"Missing"}]})
assert r["result"] is None and r["matched_row_count"] == 0
for args in [{"table_id":"other", "operation":"count"}, {"table_id":"table-1", "operation":["sum"]},
             {"table_id":"table-1", "operation":"sum", "value_column":"store"},
             {"table_id":"table-1", "operation":"count", "sql":"DROP TABLE"},
             {"table_id":"table-1", "operation":"count", "filters":[{"column":"sold", "operator":"gt", "value":float("inf")}]},
             {"table_id":"table-1", "operation":"count", "filters":[{"column":"store", "operator":["eq"], "value":"Eket"}]}]:
    assert "error" in w.execute(args), args
many = TableWorkspace([ParsedTable("many", "many.csv", pd.DataFrame({"group":range(1001)}))])
assert "error" in many.execute({"table_id":"many", "operation":"count", "group_column":"group"})
for _ in range(12):
    w.execute({"table_id":"table-1", "operation":"count"})
assert len(w.evidence) == 12 and "error" in w.execute({"table_id":"table-1", "operation":"count"})
json.dumps(w.evidence, allow_nan=False)
for values in [[True], [float("nan")], [float("inf")], [1e308,1e308]]:
    assert "error" in insight_agent._execute_aggregate({"operation":"sum", "values":values})
assert insight_agent._execute_aggregate({"operation":"sum", "values":[1e16,1,-1e16]})["result"] == 1
rates = TableWorkspace([ParsedTable("rates", "sales.csv", pd.DataFrame({
    "sold":[1.0,9.0,None], "footfall":[10.0,30.0,60.0]}))])
rate = rates.execute({"table_id":"rates", "operation":"rate", "value_column":"sold", "denominator_column":"footfall"})
assert rate["result"] == 25.0 and rate["excluded_numeric_values"] == 1
assert "error" in rates.execute({"table_id":"rates", "operation":"rate", "value_column":"sold", "denominator_column":"sold"})

workspace = TableWorkspace([ParsedTable("table-1", "september.csv", frame)])
calls = []
def create(**kwargs):
    calls.append(kwargs)
    if len(calls) == 1:
        assert "analyze_table" in [t["name"] for t in kwargs["tools"]]
        payload = json.loads(kwargs["messages"][0]["content"][0]["text"])
        assert payload["parsed_tables"][0]["parsed_row_count"] == 4
        return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", id="calc-1", name="analyze_table", input={"table_id":"table-1", "operation":"average", "value_column":"wait", "group_column":"store"})])
    result = json.loads(kwargs["messages"][-1]["content"][0]["content"])
    assert result["groups"][0]["value"] == 20 and result["evidence_id"] == "table-calculation-1"
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"what":"Eket averages 20 minutes.", "confidence":"medium"}))])
with patch.object(insight_agent, "_client", SimpleNamespace(messages=SimpleNamespace(create=create))):
    insight, charts = insight_agent.explain_document_only_v2("Which store has longer waits?", [], table_workspace=workspace)
assert "20" in insight.what and len(workspace.evidence) == 1
print("Table calculations, filters, multi-file isolation, missing values, budgets and model/tool evidence roundtrip passed")
