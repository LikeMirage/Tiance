import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import type { ConversationRoleCatalog } from "../../../entities/role-configuration/model/roleConfiguration";
import { RolePickerPanel } from "../../../entities/role-configuration/ui/RolePickerPanel";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import { applyConversationRole } from "../../../services/project/applyConversationRole";
import { getConversationRoles } from "../../../services/project/getConversationRoles";
import { saveConversationAsRole } from "../../../services/project/saveConversationAsRole";
import { SaveConversationRoleDialog } from "./SaveConversationRoleDialog";

type Props = {
  projectId: string;
  session: ConversationSession;
  onSessionUpdated: (session: ConversationSession) => void;
};

const PANEL_HEIGHT = 300;

export function ChatRoleSelector({
  projectId,
  session,
  onSessionUpdated,
}: Props) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const [catalog, setCatalog] = useState<ConversationRoleCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOpen, setIsOpen] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>();
  const [query, setQuery] = useState("");
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const loadCatalog = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getConversationRoles();
      if (requestId !== requestIdRef.current) return;
      setCatalog(result);
      setActiveCategoryId((current) => {
        if (current && result.categories.some((item) => item.category_id === current)) {
          return current;
        }
        const selectedRole = result.roles.find(
          (item) => item.role_project_id === session.role_project_id,
        );
        return selectedRole?.category_id ?? result.categories[0]?.category_id ?? null;
      });
    } catch (loadError) {
      if (requestId !== requestIdRef.current) return;
      setError(errorMessage(loadError, "角色列表加载失败"));
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  }, [session.role_project_id]);

  useEffect(() => {
    void loadCatalog();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadCatalog]);

  useLayoutEffect(() => {
    if (!isOpen) return;
    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const edge = 8;
      const width = Math.min(520, window.innerWidth - edge * 2);
      const height = Math.min(PANEL_HEIGHT, window.innerHeight - edge * 2);
      setPanelStyle({
        width,
        height,
        left: Math.min(Math.max(edge, rect.left), window.innerWidth - width - edge),
        top: Math.min(rect.bottom + 6, window.innerHeight - height - edge),
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [isOpen]);

  const filteredRoles = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!catalog || !normalized) return catalog?.roles ?? [];
    return catalog.roles.filter((role) =>
      `${role.name} ${role.description ?? ""}`.toLocaleLowerCase().includes(normalized)
    );
  }, [catalog, query]);
  const visibleCategories = useMemo(
    () => (catalog?.categories ?? []).filter((category) =>
      filteredRoles.some((role) => role.category_id === category.category_id)
    ),
    [catalog?.categories, filteredRoles],
  );
  const resolvedCategoryId =
    activeCategoryId && visibleCategories.some((item) => item.category_id === activeCategoryId)
      ? activeCategoryId
      : visibleCategories[0]?.category_id ?? null;
  const visibleRoles = filteredRoles.filter(
    (role) => role.category_id === resolvedCategoryId,
  );
  const selectedRole = catalog?.roles.find(
    (role) => role.role_project_id === session.role_project_id,
  );
  const selectedLabel =
    session.role_status === "selected" && selectedRole
      ? selectedRole.name
      : "自定义";
  const saveDialogHost =
    triggerRef.current?.closest<HTMLElement>(".ai-panel__body-frame") ?? undefined;

  const selectRole = async (roleProjectId: string) => {
    if (isApplying || roleProjectId === session.role_project_id && session.role_status === "selected") {
      setIsOpen(false);
      return;
    }
    setIsApplying(true);
    setError(null);
    try {
      const updated = await applyConversationRole(
        projectId,
        session.session_id,
        roleProjectId,
      );
      onSessionUpdated(updated);
      setIsOpen(false);
    } catch (applyError) {
      setError(errorMessage(applyError, "角色应用失败"));
    } finally {
      setIsApplying(false);
    }
  };

  const saveRole = async (name: string, categoryId: string) => {
    if (!name || !categoryId || isSaving) return;
    setIsSaving(true);
    setError(null);
    try {
      const result = await saveConversationAsRole(projectId, session.session_id, {
        name,
        category_id: categoryId,
      });
      onSessionUpdated(result.session);
      dispatchProjectCatalogChanged();
      setSaveDialogOpen(false);
      await loadCatalog();
    } catch (saveError) {
      setError(errorMessage(saveError, "角色保存失败"));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <div className="chat-role-selector">
        <span className="ai-panel__setting-label">角色</span>
        <div className="chat-role-selector__actions">
          <button
            ref={triggerRef}
            className="chat-role-selector__trigger"
            type="button"
            disabled={isLoading || isApplying}
            aria-expanded={isOpen}
            onClick={() => {
              setQuery("");
              setIsOpen((current) => !current);
            }}
          >
            <span>{isLoading ? "正在加载…" : selectedLabel}</span>
            <span className="chat-role-selector__caret" aria-hidden="true" />
          </button>
          {session.role_status === "custom" ? (
            <button
              className="chat-role-selector__save"
              type="button"
              disabled={isLoading}
              onClick={() => setSaveDialogOpen(true)}
            >
              保存为角色
            </button>
          ) : null}
        </div>
      </div>
      {error ? <div className="chat-role-selector__error">{error}</div> : null}

      {isOpen ? (
        <RolePickerPanel
          activeCategoryId={resolvedCategoryId}
          applying={isApplying}
          categories={visibleCategories}
          filteredRoles={filteredRoles}
          onCategoryChange={setActiveCategoryId}
          onClose={() => setIsOpen(false)}
          onQueryChange={setQuery}
          onRoleSelect={(roleProjectId) => void selectRole(roleProjectId)}
          panelRef={panelRef}
          panelStyle={panelStyle}
          query={query}
          roles={visibleRoles}
          selectedRoleProjectId={session.role_project_id}
        />
      ) : null}

      {saveDialogOpen ? (
        <SaveConversationRoleDialog
          categories={catalog?.categories ?? []}
          portalTarget={saveDialogHost}
          saving={isSaving}
          onCancel={() => setSaveDialogOpen(false)}
          onSave={(name, categoryId) => void saveRole(name, categoryId)}
        />
      ) : null}
    </>
  );
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
