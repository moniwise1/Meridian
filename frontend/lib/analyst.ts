// Client-side mirror of the `analysis` object backend/app/agents/analyst_contract.py
// produces and validates. Kept in its own module (rather than inside api.ts)
// because docs/ask-analysis.schema.json is generated from the Python models
// and these types have to be checked against it whenever it changes.
//
// Every numeric field here is `number | null` on purpose: null means "not
// established", which is not the same thing as zero, and the renderer must
// never quietly turn one into the other.

export type AnalystConfidenceLevel = "high" | "medium" | "low" | "not_assessable";

export type AnalystConfidence = {
  level: AnalystConfidenceLevel;
  reason: string;
};

export type AnalystColumn = {
  key: string;
  label: string;
  type: "string" | "number";
  unit: string | null;
};

export type AnalystTable = {
  id: string;
  title: string;
  columns: AnalystColumn[];
  rows: Record<string, string | number | null>[];
  evidence_ids: string[];
};

export type AnalystChart = {
  type: "bar" | "line";
  title: string;
  table_id: string;
  category_key: string;
  value_keys: string[];
};

export type AnalystMetric = {
  id: string;
  label: string;
  value: number | null;
  unit: string | null;
  evidence_ids: string[];
};

export type AnalystFinding = {
  id: string;
  kind: "observation" | "anomaly" | "hypothesis";
  text: string;
  evidence_ids: string[];
};

export type AnalystEvidence = {
  id: string;
  source_id: string;
  source_version: string | null;
  filename: string | null;
  location: string | null;
  computation_id: string;
  method: "computed" | "extracted_text";
};

export type AnalystAnalysis = {
  schema_version: "1.0";
  analysis_id: string;
  status: "complete" | "partial" | "insufficient_data" | "error";
  headline: string;
  summary: string;
  scope: {
    question: string;
    source_ids: string[];
    metric_definition: string | null;
    period: string | null;
    comparison: string | null;
    currency: string | null;
    assumptions: string[];
  };
  metrics: AnalystMetric[];
  tables: AnalystTable[];
  charts: AnalystChart[];
  findings: AnalystFinding[];
  quality: {
    row_count: number | null;
    completeness_pct: number | null;
    duplicate_pct: number | null;
    excluded_rows: number | null;
    data_through: string | null;
    limitations: string[];
  };
  confidence: { measurement: AnalystConfidence; explanation: AnalystConfidence };
  actions: { label: string; reason: string }[];
  follow_ups: { label: string; question: string }[];
  evidence: AnalystEvidence[];
};

export type AnalystWorkspaceData = {
  memories: { id: string; kind: string; content: string; confirmed: boolean }[];
  conversations: { id: string; title: string; updated_at: string }[];
  findings: {
    id: string;
    status: string;
    title: string;
    detail: string;
    confidence: string;
    kind: string;
    source_version: string | null;
  }[];
  checks: { status: string; attempts: number }[];
};
