import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  ConversationBranchGroup,
  ConversationBranchGroupDetailResponse,
} from "../../../entities/llm-chat/model/conversation";
import { listenProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { isAbortError } from "../../../services/http/httpErrors";
import { getProjectConversationBranchGroup } from "../../../services/project/getProjectConversationBranchGroup";
import { getProjectConversationBranchGroups } from "../../../services/project/getProjectConversationBranchGroups";
import {
  findActiveConversationBranchGroupId,
  shouldAutoRefreshConversationBranchDashboard,
} from "./conversationBranchRefresh";

const AUTO_REFRESH_DELAY_MS = 300;

export function useConversationBranchDashboard(
  projectId: string | null,
  activeSessionId: string | null,
  isActive = true,
) {
  const [groups, setGroups] = useState<ConversationBranchGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationBranchGroupDetailResponse | null>(null);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isLoadingGroups, setIsLoadingGroups] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const groupsRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const autoRefreshTimerRef = useRef<number | null>(null);
  const followedActiveSessionIdRef = useRef<string | null>(null);

  const clearAutoRefreshTimer = useCallback(() => {
    if (autoRefreshTimerRef.current === null) return;
    window.clearTimeout(autoRefreshTimerRef.current);
    autoRefreshTimerRef.current = null;
  }, []);
  const refresh = useCallback(() => {
    if (!isActive) return;
    clearAutoRefreshTimer();
    setRefreshVersion((version) => version + 1);
  }, [clearAutoRefreshTimer, isActive]);
  const scheduleAutoRefresh = useCallback(() => {
    if (!isActive) return;
    clearAutoRefreshTimer();
    autoRefreshTimerRef.current = window.setTimeout(() => {
      autoRefreshTimerRef.current = null;
      setRefreshVersion((version) => version + 1);
    }, AUTO_REFRESH_DELAY_MS);
  }, [clearAutoRefreshTimer, isActive]);

  useEffect(() => {
    if (!projectId) {
      groupsRequestIdRef.current += 1;
      setGroups([]);
      setSelectedGroupId(null);
      setDetail(null);
      setGroupsError(null);
      return undefined;
    }
    if (!isActive) {
      groupsRequestIdRef.current += 1;
      setIsLoadingGroups(false);
      return undefined;
    }
    const controller = new AbortController();
    const requestId = groupsRequestIdRef.current + 1;
    groupsRequestIdRef.current = requestId;
    setIsLoadingGroups(true);
    setGroupsError(null);
    void getProjectConversationBranchGroups(projectId, controller.signal)
      .then((response) => {
        if (groupsRequestIdRef.current !== requestId) return;
        setGroups(response.items);
        setSelectedGroupId((current) => {
          if (current && response.items.some((group) => group.group_id === current)) return current;
          return response.items[0]?.group_id ?? null;
        });
      })
      .catch((error) => {
        if (groupsRequestIdRef.current !== requestId || isAbortError(error)) return;
        setGroupsError(error instanceof Error ? error.message : "会话分支组加载失败。");
        setGroups([]);
        setSelectedGroupId(null);
      })
      .finally(() => {
        if (groupsRequestIdRef.current === requestId) setIsLoadingGroups(false);
      });
    return () => controller.abort();
  }, [isActive, projectId, refreshVersion]);

  useEffect(() => {
    followedActiveSessionIdRef.current = null;
  }, [projectId]);

  useEffect(() => {
    if (
      !isActive
      || !activeSessionId
      || followedActiveSessionIdRef.current === activeSessionId
    ) return;
    const activeGroupId = findActiveConversationBranchGroupId(groups, activeSessionId);
    if (!activeGroupId) return;
    followedActiveSessionIdRef.current = activeSessionId;
    setSelectedGroupId(activeGroupId);
  }, [activeSessionId, groups, isActive]);

  useEffect(() => {
    if (!isActive || !projectId) {
      clearAutoRefreshTimer();
      return undefined;
    }
    const stopListening = listenProjectConversationUpdated((event) => {
      if (!shouldAutoRefreshConversationBranchDashboard(event, projectId)) return;
      scheduleAutoRefresh();
    });
    return () => {
      stopListening();
      clearAutoRefreshTimer();
    };
  }, [clearAutoRefreshTimer, isActive, projectId, scheduleAutoRefresh]);

  useEffect(() => {
    if (!projectId || !selectedGroupId) {
      detailRequestIdRef.current += 1;
      setDetail(null);
      setDetailError(null);
      return undefined;
    }
    if (!isActive) {
      detailRequestIdRef.current += 1;
      setIsLoadingDetail(false);
      return undefined;
    }
    const controller = new AbortController();
    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setIsLoadingDetail(true);
    setDetailError(null);
    void getProjectConversationBranchGroup(projectId, selectedGroupId, controller.signal)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setDetail(response);
      })
      .catch((error) => {
        if (detailRequestIdRef.current !== requestId || isAbortError(error)) return;
        setDetailError(error instanceof Error ? error.message : "会话分支加载失败。");
        setDetail(null);
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) setIsLoadingDetail(false);
      });
    return () => controller.abort();
  }, [isActive, projectId, refreshVersion, selectedGroupId]);

  const selectedGroup = useMemo(
    () => groups.find((group) => group.group_id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );
  return {
    detail,
    detailError,
    groups,
    groupsError,
    isLoadingDetail,
    isLoadingGroups,
    refresh,
    selectedGroup,
    selectedGroupId,
    selectGroup: setSelectedGroupId,
  };
}
