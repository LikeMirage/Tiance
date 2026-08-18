import { useCallback, useEffect, useState } from "react";

import type { ToolCallRecordSummaryItem } from "../../../entities/tool/model/toolCallRecord";
import type { ToolFolder } from "../../../entities/tool/model/toolset";
import { updateToolFolderRuntimeSettings } from "../../../services/tools/updateToolFolderRuntimeSettings";

export type ToolRuntimeSwitch = "enabled" | "dynamic" | "parallel";
type ToolRuntimeOverrides = Partial<Record<ToolRuntimeSwitch, boolean>>;

export function useToolRuntimeSettings({
  itemsByFolderId,
  onReload,
  readonly,
  summaryVersion,
  toolsetId,
}: {
  itemsByFolderId: Map<string, ToolCallRecordSummaryItem>;
  onReload: () => void;
  readonly: boolean;
  summaryVersion: object | null;
  toolsetId: string | null;
}) {
  const [updatingFolderId, setUpdatingFolderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Map<string, ToolRuntimeOverrides>>(
    () => new Map(),
  );

  useEffect(() => {
    setOverrides(new Map());
  }, [toolsetId]);

  useEffect(() => {
    if (!summaryVersion) return;
    setOverrides((current) => {
      let changed = false;
      const next = new Map(current);
      for (const [folderId, values] of current) {
        const stats = itemsByFolderId.get(folderId);
        if (!stats) continue;
        const unresolved = Object.fromEntries(
          Object.entries(values).filter(([key, value]) => (
            stats[key as ToolRuntimeSwitch] !== value
          )),
        ) as ToolRuntimeOverrides;
        if (Object.keys(unresolved).length === 0) {
          next.delete(folderId);
          changed = true;
        } else if (Object.keys(unresolved).length !== Object.keys(values).length) {
          next.set(folderId, unresolved);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [itemsByFolderId, summaryVersion]);

  const resolveStats = useCallback((
    folderId: string,
    stats: ToolCallRecordSummaryItem | null,
  ) => {
    if (!stats) return null;
    const values = overrides.get(folderId);
    return {
      ...stats,
      enabled: values?.enabled ?? stats.enabled,
      dynamic: values?.dynamic ?? stats.dynamic,
      parallel: values?.parallel ?? stats.parallel,
    };
  }, [overrides]);

  const updateSetting = useCallback(async (
    folder: ToolFolder,
    stats: ToolCallRecordSummaryItem,
    setting: ToolRuntimeSwitch,
  ) => {
    const previousValue = overrides.get(folder.project_id)?.[setting] ?? stats[setting];
    if (!toolsetId || readonly || previousValue == null) return;
    const nextValue = !previousValue;
    setUpdatingFolderId(folder.project_id);
    setError(null);
    setOverrides((current) => mergeOverride(current, folder.project_id, setting, nextValue));
    try {
      await updateToolFolderRuntimeSettings(toolsetId, folder.project_id, {
        [setting]: nextValue,
      });
      onReload();
    } catch (requestError) {
      setOverrides((current) => mergeOverride(current, folder.project_id, setting, previousValue));
      setError(requestError instanceof Error ? requestError.message : "工具运行设置保存失败。");
    } finally {
      setUpdatingFolderId((current) => current === folder.project_id ? null : current);
    }
  }, [onReload, overrides, readonly, toolsetId]);

  return {
    error,
    resolveStats,
    updateSetting,
    updatingFolderId,
  };
}

function mergeOverride(
  current: Map<string, ToolRuntimeOverrides>,
  folderId: string,
  setting: ToolRuntimeSwitch,
  value: boolean,
) {
  const next = new Map(current);
  next.set(folderId, { ...next.get(folderId), [setting]: value });
  return next;
}
