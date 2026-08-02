import { fetchJson } from "../http/httpClient";

export type ToolSummary = {
  name: string;
  display_name: string;
  description: string;
  keywords: string[];
  category: string;
  dynamic: boolean;
  parallel: boolean;
  parameter_names: string[];
  example_titles: string[];
};

export type ToolSummaryListResponse = {
  count: number;
  items: ToolSummary[];
};

export function getToolSummaries(): Promise<ToolSummaryListResponse> {
  return fetchJson<ToolSummaryListResponse>("/api/tools/catalog/summaries");
}
