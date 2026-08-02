import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../../entities/llm-chat/model/conversation";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import { normalizeSessionTitleInput, resolveSessionSettings } from "./sessionSettings";

type UseSessionSettingsEditorOptions = {
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSession: ConversationSession | null;
  activeSessionId: string | null;
  activeSessionSettings: ConversationSessionSettings;
  projectId: string | null;
  reloadSessions: (pid: string) => Promise<void>;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
};

export function useSessionSettingsEditor({
  activeProjectIdRef,
  activeSession,
  activeSessionId,
  activeSessionSettings,
  projectId,
  reloadSessions,
  setSessions,
}: UseSessionSettingsEditorOptions) {
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);
  const [systemPromptDraft, setSystemPromptDraft] = useState("");
  const settingsRequestSeqRef = useRef(0);
  const titleRequestSeqRef = useRef(0);

  useEffect(() => {
    setSessionTitleDraft(activeSession?.title ?? "");
    setSystemPromptDraft(activeSessionSettings.system_prompt);
    setSaveErrorMessage(null);
  }, [activeSession?.session_id, activeSession?.title, activeSessionSettings.system_prompt]);

  const updateActiveSessionSettings = useCallback((patch: Partial<ConversationSessionSettings>) => {
    if (!projectId || !activeSessionId) return;
    const requestSeq = settingsRequestSeqRef.current + 1;
    settingsRequestSeqRef.current = requestSeq;
    const requestedProjectId = projectId;
    const requestedSessionId = activeSessionId;
    setSaveErrorMessage(null);
    setSessions((prev) => prev.map((session) =>
      session.session_id === activeSessionId
        ? {
            ...session,
            settings: {
              ...resolveSessionSettings(session),
              ...patch,
            },
            role_status: "custom",
            updated_at: new Date().toISOString(),
          }
        : session,
    ));
    void updateProjectConversation(requestedProjectId, requestedSessionId, {
      settings: patch,
    }).then((updatedSession) => {
      if (
        settingsRequestSeqRef.current !== requestSeq ||
        activeProjectIdRef.current !== requestedProjectId ||
        updatedSession.session_id !== requestedSessionId
      ) {
        return;
      }
      setSessions((prev) => prev.map((session) =>
        session.session_id === updatedSession.session_id
          ? {
              ...session,
              settings: {
                ...resolveSessionSettings(session),
                ...patch,
              },
              role_project_id: updatedSession.role_project_id,
              role_status: updatedSession.role_status,
              updated_at: updatedSession.updated_at,
            }
          : session,
      ));
    }).catch(() => {
      if (
        settingsRequestSeqRef.current === requestSeq &&
        activeProjectIdRef.current === requestedProjectId
      ) {
        setSaveErrorMessage("会话设置保存失败，已恢复。");
        void reloadSessions(requestedProjectId);
      }
    });
  }, [activeProjectIdRef, activeSessionId, projectId, reloadSessions, setSessions]);

  const saveActiveSessionTitle = useCallback(() => {
    if (!projectId || !activeSessionId || !activeSession) return;
    const title = normalizeSessionTitleInput(sessionTitleDraft);
    if (title === activeSession.title) {
      setSessionTitleDraft(title);
      return;
    }
    const requestSeq = titleRequestSeqRef.current + 1;
    titleRequestSeqRef.current = requestSeq;
    const requestedProjectId = projectId;
    const requestedSessionId = activeSessionId;
    setSaveErrorMessage(null);
    setSessionTitleDraft(title);
    setSessions((prev) => prev.map((session) =>
      session.session_id === activeSessionId
        ? { ...session, title, manual_title: true, updated_at: new Date().toISOString() }
        : session,
    ));
    void updateProjectConversation(requestedProjectId, requestedSessionId, {
      title,
    }).then((updatedSession) => {
      if (
        titleRequestSeqRef.current !== requestSeq ||
        activeProjectIdRef.current !== requestedProjectId ||
        updatedSession.session_id !== requestedSessionId
      ) {
        return;
      }
      setSessions((prev) => prev.map((session) =>
        session.session_id === updatedSession.session_id
          ? {
              ...session,
              manual_title: updatedSession.manual_title,
              title: updatedSession.title,
              updated_at: updatedSession.updated_at,
            }
          : session,
      ));
    }).catch(() => {
      if (
        titleRequestSeqRef.current === requestSeq &&
        activeProjectIdRef.current === requestedProjectId
      ) {
        setSaveErrorMessage("会话标题保存失败，已恢复。");
        void reloadSessions(requestedProjectId);
      }
    });
  }, [
    activeProjectIdRef,
    activeSession,
    activeSessionId,
    projectId,
    reloadSessions,
    sessionTitleDraft,
    setSessions,
  ]);

  const saveActiveSystemPrompt = useCallback(() => {
    const systemPrompt = systemPromptDraft;
    if (systemPrompt === activeSessionSettings.system_prompt) return;
    updateActiveSessionSettings({ system_prompt: systemPrompt });
  }, [activeSessionSettings.system_prompt, systemPromptDraft, updateActiveSessionSettings]);

  return {
    saveActiveSessionTitle,
    saveActiveSystemPrompt,
    saveErrorMessage,
    sessionTitleDraft,
    setSessionTitleDraft,
    setSystemPromptDraft,
    systemPromptDraft,
    updateActiveSessionSettings,
  };
}
