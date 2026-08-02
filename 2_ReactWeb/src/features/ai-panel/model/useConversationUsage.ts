import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import {
  getProjectConversationUsageSummary,
  type ConversationUsageSummary,
} from "../../../services/project/getProjectConversationUsageSummary";
import { getCachedProjectEntryWarmup } from "../../project-entry/model/projectEntryWarmup";
import { buildSessionKey } from "./sessionKey";
import {
  buildUsageScopeOptions,
  resolveUsageScopeSummary,
  USAGE_TOTAL_SCOPE_KEY,
} from "./usageSummary";

type UseConversationUsageOptions = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionId: string | null;
  activeSessionKey: string | null;
  isActive?: boolean;
  projectId: string | null;
};

type ReloadSessionUsageSummaryOptions = {
  forceRefresh?: boolean;
};

export function useConversationUsage({
  activeProjectIdRef,
  activeSessionId,
  activeSessionKey,
  isActive = true,
  projectId,
}: UseConversationUsageOptions) {
  const [isUsagePopoverOpen, setIsUsagePopoverOpen] = useState(false);
  const [usageScopeKey, setUsageScopeKey] = useState(USAGE_TOTAL_SCOPE_KEY);
  const [sessionUsageSummaries, setSessionUsageSummaries] =
    useState<Record<string, ConversationUsageSummary>>({});
  const usageReloadRequestIdsRef = useRef(new Map<string, number>());

  const sessionUsage = activeSessionKey ? sessionUsageSummaries[activeSessionKey] : undefined;
  const usageScopeOptions = useMemo(() => buildUsageScopeOptions(sessionUsage), [sessionUsage]);
  const selectedUsage = resolveUsageScopeSummary(sessionUsage, usageScopeKey);

  const reloadSessionUsageSummary = useCallback(async (
    pid: string,
    sessionId: string,
    options: ReloadSessionUsageSummaryOptions = {},
  ) => {
    const sessionKey = buildSessionKey(pid, sessionId);
    const requestId = (usageReloadRequestIdsRef.current.get(sessionKey) ?? 0) + 1;
    usageReloadRequestIdsRef.current.set(sessionKey, requestId);
    const cachedSummary = options.forceRefresh
      ? null
      : getCachedProjectEntryWarmup(pid)?.sessionUsageSummaries[sessionId];
    const summary = cachedSummary ?? await getProjectConversationUsageSummary(pid, sessionId);
    if (usageReloadRequestIdsRef.current.get(sessionKey) !== requestId) return;
    if (activeProjectIdRef.current !== pid) return;
    setSessionUsageSummaries((prev) => ({
      ...prev,
      [sessionKey]: summary,
    }));
  }, [activeProjectIdRef]);

  useEffect(() => {
    if (!isActive) return;
    if (!projectId || !activeSessionId) return;
    void reloadSessionUsageSummary(projectId, activeSessionId).catch(() => undefined);
  }, [activeSessionId, isActive, projectId, reloadSessionUsageSummary]);

  useEffect(() => {
    setUsageScopeKey(USAGE_TOTAL_SCOPE_KEY);
  }, [activeSessionKey]);

  useEffect(() => {
    if (usageScopeOptions.some((option) => option.value === usageScopeKey)) {
      return;
    }
    setUsageScopeKey(USAGE_TOTAL_SCOPE_KEY);
  }, [usageScopeKey, usageScopeOptions]);

  return {
    isUsagePopoverOpen,
    reloadSessionUsageSummary,
    selectedUsage,
    sessionUsage,
    setIsUsagePopoverOpen,
    setUsageScopeKey,
    usageScopeKey,
    usageScopeOptions,
  };
}
