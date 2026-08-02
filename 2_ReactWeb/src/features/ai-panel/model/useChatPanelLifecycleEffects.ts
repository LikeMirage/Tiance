import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import type { ChatMessage } from "./chatMessage";
import { buildSessionKey } from "./sessionKey";

type UseActiveSessionMessagesLoaderOptions = {
  activeSessionId: string | null;
  isActive?: boolean;
  isSessionStreaming: (sessionKey: string) => boolean;
  isNotFoundRequestError: (error: unknown) => boolean;
  projectId: string | null;
  reloadSessionMessages: (
    projectId: string,
    sessionId: string,
    options: {
      preserveLocalIfShorter?: boolean;
      forceRefresh?: boolean;
      signal?: AbortSignal;
      shouldApply?: () => boolean;
      shouldPreserveLocal?: () => boolean;
    },
  ) => Promise<boolean>;
  reloadSessions: (projectId: string) => Promise<void>;
};

type UseActiveSessionLiveReloadOptions = UseActiveSessionMessagesLoaderOptions & {
  activeRuntimeStatus: ConversationRuntimeStatus | null;
  messages: ChatMessage[];
  isActiveSessionStreaming: boolean;
};

type ActiveSessionLiveReloadMode = "off" | "session-only" | "messages-and-session";

type ResolveActiveSessionLiveReloadModeOptions = {
  activeRuntimeStatus: ConversationRuntimeStatus | null;
  hasActiveTarget: boolean;
  isActive: boolean;
  isActiveSessionStreaming: boolean;
  isCompactionRunning: boolean;
};

type UseChatPanelPopoverDismissOptions = {
  modelMenuRef: RefObject<HTMLDivElement | null>;
  setIsModelMenuOpen: Dispatch<SetStateAction<boolean>>;
  setIsUsagePopoverOpen: Dispatch<SetStateAction<boolean>>;
  usageAreaRef: RefObject<HTMLDivElement | null>;
};

export function useStreamingClockTick(isActiveSessionStreaming: boolean) {
  const [clockTick, setClockTick] = useState(() => Date.now());

  useEffect(() => {
    if (!isActiveSessionStreaming) return undefined;
    const timer = window.setInterval(() => setClockTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isActiveSessionStreaming]);

  return clockTick;
}

export function useActiveSessionMessagesLoader({
  activeSessionId,
  isActive = true,
  isSessionStreaming,
  isNotFoundRequestError,
  projectId,
  reloadSessionMessages,
  reloadSessions,
}: UseActiveSessionMessagesLoaderOptions) {
  useEffect(() => {
    if (!isActive) {
      return undefined;
    }
    let disposed = false;
    const controller = new AbortController();

    async function loadMessages() {
      if (!projectId || !activeSessionId) {
        return;
      }
      await reloadSessionMessages(projectId, activeSessionId, {
        forceRefresh: true,
        preserveLocalIfShorter: true,
        signal: controller.signal,
        shouldApply: () => !disposed,
        shouldPreserveLocal: () => isSessionStreaming(
          buildSessionKey(projectId, activeSessionId),
        ),
      });
      if (!disposed) {
        void reloadSessions(projectId).catch(() => undefined);
      }
    }

    void loadMessages().catch((err) => {
      if (projectId && isNotFoundRequestError(err)) {
        void reloadSessions(projectId);
      }
      // 当前会话加载失败时保留已有缓存，避免正在回复的本地内容被清空。
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    activeSessionId,
    isActive,
    isNotFoundRequestError,
    isSessionStreaming,
    projectId,
    reloadSessionMessages,
    reloadSessions,
  ]);
}

export function useActiveSessionLiveReload({
  activeRuntimeStatus,
  activeSessionId,
  isActive = true,
  isActiveSessionStreaming,
  isSessionStreaming,
  messages,
  projectId,
  reloadSessionMessages,
  reloadSessions,
}: UseActiveSessionLiveReloadOptions) {
  const isCompactionRunning = useMemo(
    () => findLatestCompactionRunningState(messages),
    [messages],
  );
  const reloadMode = resolveActiveSessionLiveReloadMode({
    activeRuntimeStatus,
    hasActiveTarget: Boolean(projectId && activeSessionId),
    isActive,
    isActiveSessionStreaming,
    isCompactionRunning,
  });

  useEffect(() => {
    if (reloadMode === "off") return undefined;
    if (!projectId || !activeSessionId) return undefined;
    let disposed = false;

    const refresh = () => {
      if (reloadMode === "messages-and-session") {
        void reloadSessionMessages(projectId, activeSessionId, {
          forceRefresh: true,
          preserveLocalIfShorter: true,
          shouldApply: () => !disposed,
          shouldPreserveLocal: () => isSessionStreaming(
            buildSessionKey(projectId, activeSessionId),
          ),
        }).catch(() => undefined);
      }
      void reloadSessions(projectId).catch(() => undefined);
    };

    refresh();
    const timer = window.setInterval(
      refresh,
      reloadMode === "session-only" ? 2000 : 1000,
    );
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [
    activeSessionId,
    isSessionStreaming,
    projectId,
    reloadMode,
    reloadSessionMessages,
    reloadSessions,
  ]);
}

export function resolveActiveSessionLiveReloadMode({
  activeRuntimeStatus,
  hasActiveTarget,
  isActive,
  isActiveSessionStreaming,
  isCompactionRunning,
}: ResolveActiveSessionLiveReloadModeOptions): ActiveSessionLiveReloadMode {
  if (!isActive || !hasActiveTarget) return "off";
  if (activeRuntimeStatus !== "running" && !isCompactionRunning) return "off";
  return isActiveSessionStreaming ? "session-only" : "messages-and-session";
}

function findLatestCompactionRunningState(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "system" && message.name === "memory_compaction") {
      return message.status === "running";
    }
  }
  return false;
}

export function useChatPanelPopoverDismiss({
  modelMenuRef,
  setIsModelMenuOpen,
  setIsUsagePopoverOpen,
  usageAreaRef,
}: UseChatPanelPopoverDismissOptions) {
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      const isModelPickerPortalTarget =
        target instanceof Element && target.closest(".llm-model-picker__panel");
      if (
        modelMenuRef.current &&
        !modelMenuRef.current.contains(target) &&
        !isModelPickerPortalTarget
      ) {
        setIsModelMenuOpen(false);
      }
      if (usageAreaRef.current && !usageAreaRef.current.contains(target)) {
        setIsUsagePopoverOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [modelMenuRef, setIsModelMenuOpen, setIsUsagePopoverOpen, usageAreaRef]);
}
