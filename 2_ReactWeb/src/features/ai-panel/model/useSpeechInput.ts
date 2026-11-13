import { useEffect, useRef, useSyncExternalStore } from "react";
import { SpeechCapture } from "./speechCapture";
import type { SpeechDraftOrigin } from "./speechDraft";

export function useSpeechInput(projectId: string | null, sessionId: string | null,
  draft: string, insert: (origin: SpeechDraftOrigin, text: string) => void, isActive = true) {
  const insertRef = useRef(insert);
  insertRef.current = insert;
  const managerRef = useRef<SpeechCapture | null>(null);
  if (!managerRef.current) managerRef.current = new SpeechCapture((origin, text) => insertRef.current(origin, text));
  const manager = managerRef.current;
  const view = useSyncExternalStore(manager.subscribe, () => manager.get(projectId, sessionId));
  useEffect(() => { manager.leave(isActive ? projectId : null, isActive ? sessionId : null); }, [manager, projectId, sessionId, isActive]);
  useEffect(() => () => { manager.leave(null, null); }, [manager]);
  return {
    view,
    available: !!projectId && !!sessionId && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined",
    start: (caret: number | null) => {
      if (projectId && sessionId) void manager.start({ projectId, sessionId, draft, caret });
    },
    stop: () => { if (projectId && sessionId) manager.stop(projectId, sessionId); },
    allowMicrophone: () => { if (projectId && sessionId) void manager.allowMicrophone(projectId, sessionId); },
    cancel: () => { if (projectId && sessionId) void manager.cancel(projectId, sessionId); },
  };
}

export type SpeechInputState = ReturnType<typeof useSpeechInput>;
