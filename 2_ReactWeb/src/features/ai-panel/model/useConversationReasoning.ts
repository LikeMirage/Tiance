import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import {
  normalizeLlmReasoningMode,
  withReasoningOffOption,
} from "../../../entities/llm-runtime/model/reasoningModes";
import { useI18n, type TranslationKey } from "../../../shared/i18n";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import type { OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import type { ChatModelOption } from "./chatModelOption";
import { getModelKey } from "./useChatModelOptions";
import {
  resolveReasoningMode,
  resolveSessionModel,
} from "./chatPanelReasoning";
import { useRuntimeCapabilities } from "./useRuntimeCapabilities";

type UseConversationReasoningInput = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSession: ConversationSession | null;
  activeSessionId: string | null;
  isModelLoading: boolean;
  models: ChatModelOption[];
  projectId: string | null;
  reloadSessions: (projectId: string) => Promise<void>;
  selectedModel: ChatModelOption | null;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
};

export function useConversationReasoning({
  activeProjectIdRef,
  activeSession,
  activeSessionId,
  isModelLoading,
  models,
  projectId,
  reloadSessions,
  selectedModel,
  setSessions,
}: UseConversationReasoningInput) {
  const { t } = useI18n();
  const [pendingReasoningMode, setPendingReasoningMode] =
    useState<DsLlmReasoningMode>("off");
  const reasoningUpdateSeqRef = useRef(0);
  const sessionModel = resolveSessionModel(activeSession, models);
  const isSessionModelUnavailable = Boolean(
    activeSession?.provider_id &&
    activeSession.model_id &&
    !sessionModel &&
    !isModelLoading,
  );
  const activeModel = isSessionModelUnavailable
    ? null
    : sessionModel ?? selectedModel;
  const activeModelKey = activeModel ? getModelKey(activeModel) : null;
  const runtimeCapabilities = useRuntimeCapabilities(activeModel, activeModelKey);
  const supportedReasoningModes = useMemo(
    () => runtimeCapabilities?.reasoning.supported
      ? withReasoningOffOption(runtimeCapabilities.reasoning.modes)
      : [],
    [runtimeCapabilities],
  );
  const reasoningOptions = useMemo<Array<OptionSelectItem<DsLlmReasoningMode>>>(
    () => supportedReasoningModes.map((mode) => ({
      label: t(getReasoningModeLabelKey(mode)),
      value: mode,
    })),
    [supportedReasoningModes, t],
  );
  const activeReasoningMode = resolveReasoningMode(
    activeSession?.reasoning_mode ?? pendingReasoningMode,
    supportedReasoningModes,
  );
  const shouldShowReasoningControl = Boolean(
    activeModel && supportedReasoningModes.length > 0,
  );

  const updateActiveReasoningMode = useCallback((
    mode: DsLlmReasoningMode | null,
  ) => {
    const normalizedMode = mode ?? null;
    const updateSeq = reasoningUpdateSeqRef.current + 1;
    reasoningUpdateSeqRef.current = updateSeq;
    setPendingReasoningMode(normalizedMode ?? "off");
    if (!projectId || !activeSessionId) {
      return;
    }

    setSessions((prev) => prev.map((session) =>
      session.session_id === activeSessionId
        ? {
            ...session,
            reasoning_mode: normalizedMode,
            role_status: "custom",
            updated_at: new Date().toISOString(),
          }
        : session,
    ));

    void updateProjectConversation(projectId, activeSessionId, {
      reasoning_mode: normalizedMode,
    }).then((updatedSession) => {
      if (reasoningUpdateSeqRef.current !== updateSeq) {
        return;
      }
      if (activeProjectIdRef.current !== projectId) {
        return;
      }

      setSessions((prev) => prev.map((session) =>
        session.session_id === updatedSession.session_id
          ? {
              ...updatedSession,
              provider_id: session.provider_id,
              model_id: session.model_id,
            }
          : session,
      ));
    }).catch(() => {
      if (reasoningUpdateSeqRef.current !== updateSeq) {
        return;
      }
      void reloadSessions(projectId);
    });
  }, [
    activeProjectIdRef,
    activeSessionId,
    projectId,
    reloadSessions,
    setSessions,
  ]);

  useEffect(() => {
    if (!activeModel || !runtimeCapabilities) {
      return;
    }

    const normalizedMode = supportedReasoningModes.length > 0
      ? resolveReasoningMode(
          activeSession?.reasoning_mode ?? pendingReasoningMode,
          supportedReasoningModes,
        )
      : null;
    const currentMode =
      normalizeLlmReasoningMode(activeSession?.reasoning_mode) ?? null;

    if (activeSession && currentMode !== normalizedMode) {
      updateActiveReasoningMode(normalizedMode);
      return;
    }

    if (!activeSession && pendingReasoningMode !== (normalizedMode ?? "off")) {
      setPendingReasoningMode(normalizedMode ?? "off");
    }
  }, [
    activeModel,
    activeSession,
    pendingReasoningMode,
    runtimeCapabilities,
    supportedReasoningModes,
    updateActiveReasoningMode,
  ]);

  return {
    activeModel,
    activeReasoningMode,
    reasoningOptions,
    runtimeCapabilities,
    shouldShowReasoningControl,
    supportedReasoningModes,
    updateActiveReasoningMode,
  };
}

function getReasoningModeLabelKey(mode: DsLlmReasoningMode): TranslationKey {
  switch (mode) {
    case "default":
      return "aiPanel.reasoningModes.default";
    case "auto":
      return "aiPanel.reasoningModes.auto";
    case "enabled":
      return "aiPanel.reasoningModes.enabled";
    case "off":
      return "aiPanel.reasoningModes.off";
    case "low":
      return "aiPanel.reasoningModes.low";
    case "medium":
      return "aiPanel.reasoningModes.medium";
    case "high":
      return "aiPanel.reasoningModes.high";
    case "max":
      return "aiPanel.reasoningModes.max";
  }
}
