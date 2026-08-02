import { useCallback, useEffect, useRef, useState } from "react";

import {
  getTokenEstimationSettings,
  saveTokenEstimationSettings,
  type TokenEstimationSettings,
} from "../../../services/llm/tokenEstimationSettings";

const TOKEN_ESTIMATION_AUTO_SAVE_DELAY_MS = 500;

export function useTokenEstimationSettings() {
  const [draft, setDraft] = useState<TokenEstimationSettings | null>(null);
  const [saved, setSaved] = useState<TokenEstimationSettings | null>(null);
  const [defaults, setDefaults] = useState<TokenEstimationSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const pendingSaveRef = useRef<TokenEstimationSettings | null>(null);
  const isSavingRef = useRef(false);
  const isMountedRef = useRef(false);

  useEffect(() => {
    let isStale = false;

    async function load() {
      setIsLoading(true);
      try {
        const response = await getTokenEstimationSettings();
        if (isStale) return;
        setDraft(response.settings);
        setSaved(response.settings);
        setDefaults(response.default_settings);
        setError(null);
      } catch (loadError) {
        if (!isStale) {
          setError(toErrorMessage(loadError, "Token 估算设置载入失败。"));
        }
      } finally {
        if (!isStale) {
          setIsLoading(false);
        }
      }
    }

    void load();
    return () => {
      isStale = true;
    };
  }, []);

  const updateSetting = useCallback(
    <K extends keyof TokenEstimationSettings>(
      key: K,
      value: TokenEstimationSettings[K],
    ) => {
      setDraft((current) => current ? { ...current, [key]: value } : current);
    },
    [],
  );

  const drainSaveQueue = useCallback(async function drainSaveQueue() {
    if (isSavingRef.current) return;
    const next = pendingSaveRef.current;
    if (!next) return;
    pendingSaveRef.current = null;
    isSavingRef.current = true;
    try {
      const response = await saveTokenEstimationSettings(next);
      if (isMountedRef.current) {
        setDraft((current) =>
          current && settingsEqual(current, next) ? response.settings : current,
        );
        setSaved(response.settings);
        setDefaults(response.default_settings);
        setError(null);
      }
    } catch (saveError) {
      if (isMountedRef.current) {
        setError(toErrorMessage(saveError, "Token 估算设置保存失败。"));
      }
    } finally {
      isSavingRef.current = false;
      if (pendingSaveRef.current) {
        void drainSaveQueue();
      }
    }
  }, []);

  const queueSave = useCallback((next: TokenEstimationSettings) => {
    pendingSaveRef.current = next;
    void drainSaveQueue();
  }, [drainSaveQueue]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      void drainSaveQueue();
    };
  }, [drainSaveQueue]);

  useEffect(() => {
    if (
      isLoading
      || !draft
      || !saved
      || settingsEqual(draft, saved)
    ) {
      return undefined;
    }
    const next = draft;
    pendingSaveRef.current = next;
    const timer = window.setTimeout(() => {
      queueSave(next);
    }, TOKEN_ESTIMATION_AUTO_SAVE_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [draft, isLoading, queueSave, saved]);

  const reset = useCallback(() => {
    if (defaults) {
      setDraft(defaults);
    }
  }, [defaults]);

  return {
    draft,
    error,
    isLoading,
    reset,
    updateSetting,
  };
}

function settingsEqual(
  left: TokenEstimationSettings,
  right: TokenEstimationSettings,
) {
  return (
    left.ascii_chars_per_token === right.ascii_chars_per_token
    && left.other_chars_per_token === right.other_chars_per_token
    && left.message_overhead_tokens === right.message_overhead_tokens
    && left.image_placeholder_tokens === right.image_placeholder_tokens
  );
}

function toErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
