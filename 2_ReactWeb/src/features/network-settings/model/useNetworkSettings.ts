import { useCallback, useEffect, useState } from "react";

import {
  diagnoseGithubConnection,
  getNetworkSettings,
  saveNetworkSettings,
  type NetworkDiagnosticResponse,
  type NetworkSettings,
} from "../../../services/network/networkSettings";

export function useNetworkSettings() {
  const [draft, setDraft] = useState<NetworkSettings | null>(null);
  const [saved, setSaved] = useState<NetworkSettings | null>(null);
  const [defaults, setDefaults] = useState<NetworkSettings | null>(null);
  const [diagnostic, setDiagnostic] = useState<NetworkDiagnosticResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDiagnosing, setIsDiagnosing] = useState(false);

  useEffect(() => {
    let isStale = false;
    async function load() {
      try {
        const response = await getNetworkSettings();
        if (isStale) return;
        setDraft(response.settings);
        setSaved(response.settings);
        setDefaults(response.default_settings);
        setError(null);
      } catch (loadError) {
        if (!isStale) {
          setError(toErrorMessage(loadError, "网络设置载入失败。"));
        }
      } finally {
        if (!isStale) setIsLoading(false);
      }
    }
    void load();
    return () => {
      isStale = true;
    };
  }, []);

  const updateSetting = useCallback(
    <K extends keyof NetworkSettings>(key: K, value: NetworkSettings[K]) => {
      setDraft((current) => current ? { ...current, [key]: value } : current);
      setDiagnostic(null);
    },
    [],
  );

  const save = useCallback(async () => {
    if (!draft || isSaving) return;
    setIsSaving(true);
    try {
      const response = await saveNetworkSettings(draft);
      setDraft(response.settings);
      setSaved(response.settings);
      setDefaults(response.default_settings);
      setError(null);
    } catch (saveError) {
      setError(toErrorMessage(saveError, "网络设置保存失败。"));
    } finally {
      setIsSaving(false);
    }
  }, [draft, isSaving]);

  const reset = useCallback(() => {
    if (defaults) {
      setDraft(defaults);
      setDiagnostic(null);
    }
  }, [defaults]);

  const diagnoseGithub = useCallback(async () => {
    if (isDiagnosing) return;
    setIsDiagnosing(true);
    try {
      const response = await diagnoseGithubConnection();
      setDiagnostic(response);
      setError(null);
    } catch (diagnosticError) {
      setDiagnostic(null);
      setError(toErrorMessage(diagnosticError, "GitHub 连通性检测失败。"));
    } finally {
      setIsDiagnosing(false);
    }
  }, [isDiagnosing]);

  return {
    diagnostic,
    draft,
    error,
    hasChanges: Boolean(draft && saved && !settingsEqual(draft, saved)),
    isDiagnosing,
    isLoading,
    isSaving,
    diagnoseGithub,
    reset,
    save,
    updateSetting,
  };
}

function settingsEqual(left: NetworkSettings, right: NetworkSettings) {
  return (Object.keys(left) as Array<keyof NetworkSettings>).every(
    (key) => left[key] === right[key],
  );
}

function toErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
