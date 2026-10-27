import {
  useEffect,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { buildSessionKey } from "./sessionKey";
import { getConversationMessageState, watchConversationChanges, type ConversationMessageState } from "../../../services/project/watchConversationChanges";

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

type UseActiveSessionLiveReloadOptions = UseActiveSessionMessagesLoaderOptions;

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

    async function loadMessages() {
      if (!projectId || !activeSessionId) {
        return;
      }
      await reloadSessionMessages(projectId, activeSessionId, {
        forceRefresh: true,
        preserveLocalIfShorter: true,
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
  activeSessionId, isActive = true, isSessionStreaming,
  projectId, reloadSessionMessages, reloadSessions,
}: UseActiveSessionLiveReloadOptions) {
  useEffect(() => {
    if (!isActive || !projectId || !activeSessionId) return undefined;
    let disposed = false;
    let previous: ConversationMessageState | null = null;
    let fallback: ReturnType<typeof setInterval> | null = null;
    let checking = false;
    const refresh = (state: ConversationMessageState, ready = false) => {
      if (disposed) return;
      if (ready && fallback !== null) { clearInterval(fallback); fallback = null; }
      if (ready || state.project_revision !== previous?.project_revision) {
        void reloadSessions(projectId).catch(() => undefined);
      }
      if (ready || state.revision !== previous?.revision || state.reset_revision !== previous?.reset_revision) {
        void reloadSessionMessages(projectId, activeSessionId, {
          forceRefresh: true,
          shouldPreserveLocal: () => isSessionStreaming(buildSessionKey(projectId, activeSessionId)),
        }).catch(() => undefined);
      }
      previous = state;
    };
    const reconcile = async () => {
      if (checking || disposed) return;
      checking = true;
      try { refresh(await getConversationMessageState(projectId, activeSessionId)); }
      catch { /* The history loader owns visible errors; reconnect will retry. */ }
      finally { checking = false; }
    };
    const stop = watchConversationChanges(projectId, activeSessionId, {
      onChange: refresh,
      onDisconnect: () => {
        if (!disposed && fallback === null) fallback = setInterval(() => void reconcile(), 15_000);
      },
    });
    const onVisible = () => { if (document.visibilityState === "visible") void reconcile(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      disposed = true;
      stop();
      if (fallback !== null) clearInterval(fallback);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [activeSessionId, isActive, isSessionStreaming, projectId, reloadSessionMessages, reloadSessions]);
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
