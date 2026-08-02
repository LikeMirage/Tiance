import { useCallback, useEffect, useRef, useState } from "react";

import type { ConversationRoleCatalog } from "../../../entities/role-configuration/model/roleConfiguration";
import { listenProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  getFunctionalModelProfileSettings,
  saveFunctionalModelProfileSettings,
} from "../../../services/llm/functionalModelSettings";
import { getConversationRoles } from "../../../services/project/getConversationRoles";

type DefaultConversationRoleSettings = {
  roleProjectId: string;
};

export function useDefaultConversationRoleSettings() {
  const requestIdRef = useRef(0);
  const isMountedRef = useRef(true);
  const isSavingRef = useRef(false);
  const [catalog, setCatalog] = useState<ConversationRoleCatalog | null>(null);
  const [settingsVersion, setSettingsVersion] = useState<number | null>(null);
  const [selectedRoleProjectId, setSelectedRoleProjectId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const nextCatalog = await getConversationRoles();
      const response = await getFunctionalModelProfileSettings("defaultConversation");
      if (requestId !== requestIdRef.current) return;
      const settings = normalizeSettings(
        response.settings,
        nextCatalog.default_role_project_id,
      );
      const selectedId = nextCatalog.roles.some(
        (role) => role.role_project_id === settings.roleProjectId,
      )
        ? settings.roleProjectId
        : nextCatalog.default_role_project_id;
      setCatalog(nextCatalog);
      setSettingsVersion(
        typeof response.version === "number" ? response.version : null,
      );
      setSelectedRoleProjectId(selectedId);
    } catch (loadError) {
      if (requestId !== requestIdRef.current) return;
      setError(errorMessage(loadError, "默认会话角色加载失败。"));
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    void load();
    const stopListening = listenProjectCatalogChanged(() => {
      void load();
    });
    return () => {
      isMountedRef.current = false;
      requestIdRef.current += 1;
      stopListening();
    };
  }, [load]);

  const selectRole = useCallback(async (roleProjectId: string) => {
    if (
      isSavingRef.current
      || settingsVersion === null
      || !catalog?.roles.some((role) => role.role_project_id === roleProjectId)
    ) {
      return false;
    }
    const previousRoleProjectId = selectedRoleProjectId;
    isSavingRef.current = true;
    setSelectedRoleProjectId(roleProjectId);
    setIsSaving(true);
    setError(null);
    try {
      await saveFunctionalModelProfileSettings("defaultConversation", {
        settings: { roleProjectId } satisfies DefaultConversationRoleSettings,
        version: settingsVersion,
      });
      return true;
    } catch (saveError) {
      if (isMountedRef.current) {
        setSelectedRoleProjectId(previousRoleProjectId);
        setError(errorMessage(saveError, "默认会话角色保存失败。"));
      }
      return false;
    } finally {
      isSavingRef.current = false;
      if (isMountedRef.current) setIsSaving(false);
    }
  }, [
    catalog?.roles,
    selectedRoleProjectId,
    settingsVersion,
  ]);

  return {
    catalog,
    error,
    isLoading,
    isSaving,
    load,
    selectRole,
    selectedRoleProjectId,
  };
}

function normalizeSettings(
  input: unknown,
  fallbackRoleProjectId: string,
): DefaultConversationRoleSettings {
  if (!isRecord(input) || typeof input.roleProjectId !== "string") {
    return { roleProjectId: fallbackRoleProjectId };
  }
  return {
    roleProjectId: input.roleProjectId.trim() || fallbackRoleProjectId,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
