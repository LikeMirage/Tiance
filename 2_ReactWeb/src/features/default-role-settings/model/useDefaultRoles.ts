import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationRoleCatalog } from "../../../entities/role-configuration/model/roleConfiguration";
import { listenProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import { getConversationRoles } from "../../../services/project/getConversationRoles";
import { getDefaultRoles, saveDefaultRole, type DefaultRoles, type DefaultRoleCollection } from "../../../services/project/defaultRoles";

export function useDefaultRoles() {
  const [catalog, setCatalog] = useState<ConversationRoleCatalog | null>(null);
  const [defaults, setDefaults] = useState<DefaultRoles | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const saving = useRef(false);
  const loading = useRef(true);
  const reloadAfterSave = useRef(false);

  const load = useCallback(async () => {
    if (saving.current) { reloadAfterSave.current = true; return; }
    const request = ++generation.current;
    loading.current = true;
    setIsLoading(true);
    setError(null);
    try {
      const nextCatalog = await getConversationRoles();
      const nextDefaults = await getDefaultRoles();
      if (!mounted.current || request !== generation.current) return;
      setCatalog(nextCatalog);
      setDefaults(nextDefaults);
    } catch (reason) {
      if (mounted.current && request === generation.current) setError(String(reason));
    } finally {
      if (mounted.current && request === generation.current) {
        loading.current = false;
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const stop = listenProjectCatalogChanged(() => void load());
    return () => { mounted.current = false; generation.current++; stop(); };
  }, [load]);

  const select = useCallback(async (collection: DefaultRoleCollection, roleId: string) => {
    if (saving.current || loading.current || !catalog?.roles.some(role => role.role_project_id === roleId)) return false;
    saving.current = true;
    generation.current++;
    setIsSaving(true);
    setError(null);
    try {
      const saved = await saveDefaultRole(collection, roleId);
      if (mounted.current) setDefaults(current => current ? { ...current, [collection]: saved.role_project_id } : current);
      return true;
    } catch (reason) {
      if (mounted.current) setError(String(reason));
      return false;
    } finally {
      saving.current = false;
      if (mounted.current) {
        setIsSaving(false);
        if (reloadAfterSave.current) { reloadAfterSave.current = false; void load(); }
      }
    }
  }, [catalog, load]);
  return { catalog, defaults, error, isLoading, isSaving, load, select };
}
