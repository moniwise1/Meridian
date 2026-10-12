export type OverviewInput = {
  document_id: string; sheet: number; date_column: string;
  revenue_column: string | null; expense_column: string | null;
  group_column?: string | null; group_value?: string | null; rank_by?: "revenue" | "expenses";
  currency_column: string | null; currency: string; include_duplicates: boolean;
  start: string; end: string; question?: string; detail_date?: string | null;
};
export type Overview = {
  currency: string; period: { start: string; end: string };
  previous_period: { start: string; end: string };
  metrics: { id: string; label: string; value: string | null; previous: string | null;
    change_pct: string | null; formula: string; unavailable_reason: string | null }[];
  trend: { date: string; revenue: string | null; expenses: string | null }[];
  records: { source_row: number; date: string; revenue: string | null; expenses: string | null }[];
  breakdown: { group: string | null; row_count: number; revenue: string | null; expenses: string | null }[];
  group_column: string | null; group_filter: string | null; group_count: number; breakdown_truncated: boolean;
  record_count: number; detail_date: string | null; detail_count: number; records_truncated: boolean; duplicates_included: number;
  limitations: string[]; source: { id: string; filename: string; version: string | null; uploaded_at: string; sheet: number };
  generated_at: string; answer?: string;
};
