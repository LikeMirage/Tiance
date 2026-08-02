import { useEffect, useRef } from "react";

import { saveFunctionalModelProfileSettings } from "../../../services/llm/functionalModelSettings";
import type {
  FunctionalModelProfileKey,
  FunctionalModelProfileSettingsMap,
} from "./functionalModelSettings";

type QueuedFunctionalModelSettingsSaveOptions<K extends FunctionalModelProfileKey> = {
  canSaveSettings: boolean;
  hasLoadedPersistentSettings: boolean;
  onSaveError: (message: string) => void;
  profileKey: K;
  settings: FunctionalModelProfileSettingsMap[K];
  settingsVersion: number;
};

type PendingFunctionalModelSettingsSave = {
  profileKey: FunctionalModelProfileKey;
  settings: unknown;
  settingsVersion: number;
};

const FUNCTIONAL_MODEL_SETTINGS_SAVE_DELAY_MS = 500;

export function useQueuedFunctionalModelSettingsSave<K extends FunctionalModelProfileKey>({
  canSaveSettings,
  hasLoadedPersistentSettings,
  onSaveError,
  profileKey,
  settings,
  settingsVersion,
}: QueuedFunctionalModelSettingsSaveOptions<K>) {
  const latestSaveRef = useRef<PendingFunctionalModelSettingsSave | null>(null);
  const hasPendingSaveRef = useRef(false);
  const isSavingRef = useRef(false);
  const isMountedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);
  const onSaveErrorRef = useRef(onSaveError);

  onSaveErrorRef.current = onSaveError;

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      void drainSaveQueue();
    };
  }, []);

  useEffect(() => {
    if (!hasLoadedPersistentSettings || !canSaveSettings) {
      return;
    }

    latestSaveRef.current = {
      profileKey,
      settings,
      settingsVersion,
    };
    hasPendingSaveRef.current = true;

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      void drainSaveQueue();
    }, FUNCTIONAL_MODEL_SETTINGS_SAVE_DELAY_MS);

    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [canSaveSettings, hasLoadedPersistentSettings, profileKey, settings, settingsVersion]);

  async function drainSaveQueue() {
    if (isSavingRef.current) {
      return;
    }

    const pendingSave = latestSaveRef.current;
    if (!pendingSave || !hasPendingSaveRef.current) {
      return;
    }

    hasPendingSaveRef.current = false;
    isSavingRef.current = true;
    try {
      await saveFunctionalModelProfileSettings(pendingSave.profileKey, {
        settings: pendingSave.settings,
        version: pendingSave.settingsVersion,
      });
    } catch (saveError: unknown) {
      if (isMountedRef.current) {
        onSaveErrorRef.current(
          saveError instanceof Error ? saveError.message : "功能模型设置保存失败。",
        );
      }
    } finally {
      isSavingRef.current = false;
      if (hasPendingSaveRef.current) {
        void drainSaveQueue();
      }
    }
  }
}
