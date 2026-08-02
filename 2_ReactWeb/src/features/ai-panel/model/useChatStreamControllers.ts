import { useCallback, useEffect, useRef } from "react";

export function useChatStreamControllers() {
  const streamControllersRef = useRef(new Map<string, AbortController>());

  useEffect(() => () => {
    for (const controller of streamControllersRef.current.values()) {
      controller.abort();
    }
    streamControllersRef.current.clear();
  }, []);

  const abortSessionStream = useCallback((sessionKey: string) => {
    const controller = streamControllersRef.current.get(sessionKey);
    if (!controller) {
      return;
    }
    controller.abort();
    streamControllersRef.current.delete(sessionKey);
  }, []);

  const abortProjectStreams = useCallback((projectId: string) => {
    for (const key of Array.from(streamControllersRef.current.keys())) {
      if (key.startsWith(`${projectId}:`)) {
        abortSessionStream(key);
      }
    }
  }, [abortSessionStream]);

  const createSessionStreamController = useCallback((sessionKey: string) => {
    abortSessionStream(sessionKey);
    const controller = new AbortController();
    streamControllersRef.current.set(sessionKey, controller);
    return controller;
  }, [abortSessionStream]);

  const releaseSessionStreamController = useCallback((
    sessionKey: string,
    controller: AbortController,
  ) => {
    if (streamControllersRef.current.get(sessionKey) === controller) {
      streamControllersRef.current.delete(sessionKey);
    }
  }, []);

  return {
    abortProjectStreams,
    abortSessionStream,
    createSessionStreamController,
    releaseSessionStreamController,
  };
}
