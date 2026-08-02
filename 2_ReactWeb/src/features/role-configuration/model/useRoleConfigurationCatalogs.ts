import { useEffect, useState } from "react";

import type { LlmModelCatalogEntry } from "../../../entities/llm-provider/model/modelCatalog";
import { subscribeLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { subscribeToolCatalogChanges } from "../../../entities/tool/model/toolCatalogEvents";
import { getModelCatalog } from "../../../services/llm/getModelCatalog";
import {
  getToolSummaries,
  type ToolSummary,
} from "../../../services/tools/getToolSummaries";

export function useRoleConfigurationCatalogs() {
  const [models, setModels] = useState<LlmModelCatalogEntry[]>([]);
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [modelRefreshKey, setModelRefreshKey] = useState(0);
  const [toolRefreshKey, setToolRefreshKey] = useState(0);

  useEffect(() => {
    let disposed = false;
    setModelsLoading(true);
    setModelsError(null);
    void getModelCatalog({ kind: "chat" })
      .then((response) => {
        if (!disposed) setModels(response.items);
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setModelsError(error instanceof Error ? error.message : "模型列表读取失败。");
        }
      })
      .finally(() => {
        if (!disposed) setModelsLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [modelRefreshKey]);

  useEffect(() => {
    let disposed = false;
    setToolsError(null);
    void getToolSummaries()
      .then((response) => {
        if (!disposed) setTools(response.items);
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setToolsError(error instanceof Error ? error.message : "工具列表读取失败。");
        }
      });
    return () => {
      disposed = true;
    };
  }, [toolRefreshKey]);

  useEffect(() =>
    subscribeLlmModelCatalogChanged(() => {
      setModelRefreshKey((current) => current + 1);
    }),
  []);

  useEffect(() =>
    subscribeToolCatalogChanges(() => {
      setToolRefreshKey((current) => current + 1);
    }),
  []);

  return {
    models,
    modelsError,
    modelsLoading,
    tools,
    toolsError,
  };
}
