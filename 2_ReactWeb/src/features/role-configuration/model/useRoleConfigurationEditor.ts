import { useCallback, useEffect, useRef, useState } from "react";

import {
  type RoleConfiguration,
  type RoleConfigurationSection,
  type RoleConfigurationSectionValueMap,
  ROLE_CONFIGURATION_SECTIONS,
} from "../../../entities/role-configuration/model/roleConfiguration";
import {
  loadRoleConfiguration,
  saveRoleConfigurationSection,
} from "../../../services/project/roleConfigurationFiles";

type EditorState = "idle" | "loading" | "ready" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";

const SAVE_DELAY_MS = 500;

export function useRoleConfigurationEditor(projectId: string | null) {
  const [configuration, setConfiguration] = useState<RoleConfiguration | null>(null);
  const [state, setState] = useState<EditorState>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const configurationRef = useRef<RoleConfiguration | null>(null);
  const mtimesRef = useRef<Partial<Record<RoleConfigurationSection, number>>>({});
  const dirtySectionsRef = useRef(new Set<RoleConfigurationSection>());
  const saveTimerRef = useRef<number | null>(null);
  const loadRequestIdRef = useRef(0);
  const saveRequestIdRef = useRef(0);
  const isSavingRef = useRef(false);

  const savePending = useCallback(async () => {
    if (!projectId || isSavingRef.current || !configurationRef.current) return;
    const sections = [...dirtySectionsRef.current];
    if (sections.length === 0) return;

    isSavingRef.current = true;
    saveRequestIdRef.current += 1;
    const requestId = saveRequestIdRef.current;
    const snapshot = configurationRef.current;
    setSaveState("saving");
    setSaveError(null);

    let saveSucceeded = false;
    try {
      const results = await Promise.all(
        sections.map(async (section) => {
          const expectedMtimeMs = mtimesRef.current[section];
          if (expectedMtimeMs === undefined) {
            throw new Error(`${section}.json 缺少修改时间，无法安全保存。`);
          }
          const node = await saveRoleConfigurationSection(
            projectId,
            section,
            snapshot[section],
            expectedMtimeMs,
          );
          return [section, node.mtime_ms] as const;
        }),
      );
      if (saveRequestIdRef.current !== requestId) return;
      for (const [section, mtimeMs] of results) {
        if (typeof mtimeMs === "number") {
          mtimesRef.current[section] = mtimeMs;
        }
        if (configurationRef.current?.[section] === snapshot[section]) {
          dirtySectionsRef.current.delete(section);
        }
      }
      setSaveState(dirtySectionsRef.current.size > 0 ? "idle" : "saved");
      saveSucceeded = true;
    } catch (error) {
      if (saveRequestIdRef.current !== requestId) return;
      setSaveState("error");
      setSaveError(error instanceof Error ? error.message : "角色配置保存失败。");
    } finally {
      if (saveRequestIdRef.current === requestId) {
        isSavingRef.current = false;
        if (saveSucceeded && dirtySectionsRef.current.size > 0) {
          if (saveTimerRef.current !== null) {
            window.clearTimeout(saveTimerRef.current);
          }
          saveTimerRef.current = window.setTimeout(() => {
            void savePending();
          }, SAVE_DELAY_MS);
        }
      }
    }
  }, [projectId]);

  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      void savePending();
    }, SAVE_DELAY_MS);
  }, [savePending]);

  const updateSection = useCallback(<Section extends RoleConfigurationSection>(
    section: Section,
    value: RoleConfigurationSectionValueMap[Section],
  ) => {
    setConfiguration((current) => {
      if (!current) return current;
      const next = { ...current, [section]: value };
      configurationRef.current = next;
      return next;
    });
    dirtySectionsRef.current.add(section);
    setSaveState("idle");
    setSaveError(null);
    scheduleSave();
  }, [scheduleSave]);

  const reload = useCallback(() => {
    if (!projectId) return;
    loadRequestIdRef.current += 1;
    const requestId = loadRequestIdRef.current;
    setState("loading");
    setLoadError(null);
    setSaveError(null);
    setSaveState("idle");
    void loadRoleConfiguration(projectId)
      .then((loaded) => {
        if (loadRequestIdRef.current !== requestId) return;
        configurationRef.current = loaded.configuration;
        mtimesRef.current = loaded.mtimes;
        dirtySectionsRef.current.clear();
        setConfiguration(loaded.configuration);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (loadRequestIdRef.current !== requestId) return;
        configurationRef.current = null;
        setConfiguration(null);
        setState("error");
        setLoadError(error instanceof Error ? error.message : "角色配置读取失败。");
      });
  }, [projectId]);

  useEffect(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    loadRequestIdRef.current += 1;
    saveRequestIdRef.current += 1;
    isSavingRef.current = false;
    dirtySectionsRef.current.clear();
    configurationRef.current = null;
    mtimesRef.current = {};
    setConfiguration(null);
    setLoadError(null);
    setSaveError(null);
    setSaveState("idle");

    if (!projectId) {
      setState("idle");
      return;
    }
    reload();

    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [projectId, reload]);

  return {
    configuration,
    loadError,
    reload,
    saveError,
    saveState,
    state,
    updateSection,
  };
}

export type RoleConfigurationEditor = ReturnType<typeof useRoleConfigurationEditor>;
