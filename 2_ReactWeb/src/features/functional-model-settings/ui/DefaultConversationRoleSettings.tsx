import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { RolePickerPanel } from "../../../entities/role-configuration/ui/RolePickerPanel";
import { useI18n } from "../../../shared/i18n";
import { useDefaultConversationRoleSettings } from "../model/useDefaultConversationRoleSettings";

const TITLE_ID = "functional-models-default-conversation-role-title";
const PANEL_HEIGHT = 300;

export function DefaultConversationRoleSettings() {
  const { t } = useI18n();
  const roleSettings = useDefaultConversationRoleSettings();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>();
  const [query, setQuery] = useState("");
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);

  const filteredRoles = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!roleSettings.catalog || !normalized) return roleSettings.catalog?.roles ?? [];
    return roleSettings.catalog.roles.filter((role) =>
      `${role.name} ${role.description ?? ""}`
        .toLocaleLowerCase()
        .includes(normalized)
    );
  }, [query, roleSettings.catalog]);
  const visibleCategories = useMemo(
    () => (roleSettings.catalog?.categories ?? []).filter((category) =>
      filteredRoles.some((role) => role.category_id === category.category_id)
    ),
    [filteredRoles, roleSettings.catalog?.categories],
  );
  const resolvedCategoryId =
    activeCategoryId && visibleCategories.some(
      (category) => category.category_id === activeCategoryId,
    )
      ? activeCategoryId
      : visibleCategories[0]?.category_id ?? null;
  const visibleRoles = filteredRoles.filter(
    (role) => role.category_id === resolvedCategoryId,
  );
  const selectedRole = roleSettings.catalog?.roles.find(
    (role) => role.role_project_id === roleSettings.selectedRoleProjectId,
  );

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
      if (
        triggerRef.current?.contains(target)
        || panelRef.current?.contains(target)
      ) {
        return;
      }
      setIsOpen(false);
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [isOpen]);

  return (
    <section className="functional-model-settings__section" aria-labelledby={TITLE_ID}>
      <header className="functional-model-settings__head">
        <div>
          <h2 id={TITLE_ID} className="functional-model-settings__title">
            {t("functionalModelSettings.sections.defaultConversation")}
          </h2>
        </div>
        <button
          className="functional-model-settings__secondary"
          type="button"
          disabled={
            roleSettings.isLoading
            || roleSettings.isSaving
            || !roleSettings.catalog
          }
          onClick={() => {
            const defaultRoleId = roleSettings.catalog?.default_role_project_id;
            if (defaultRoleId) void roleSettings.selectRole(defaultRoleId);
          }}
        >
          {t("common.actions.reset")}
        </button>
      </header>

      <div className="functional-model-settings__form">
        <div className="functional-model-settings__field">
          <span className="functional-model-settings__label">
            {t("functionalModelSettings.defaultConversation.role")}
          </span>
          <span className="functional-model-settings__field-description">
            {t("functionalModelSettings.defaultConversation.description")}
          </span>
          <button
            ref={triggerRef}
            className="functional-model-settings__role-picker-trigger"
            type="button"
            disabled={roleSettings.isLoading || roleSettings.isSaving}
            aria-expanded={isOpen}
            onClick={() => {
              setQuery("");
              setActiveCategoryId(selectedRole?.category_id ?? null);
              setIsOpen((current) => !current);
            }}
          >
            <span>
              {roleSettings.isLoading
                ? t("common.status.loading")
                : selectedRole?.name
                  ?? t("common.status.unavailable")}
            </span>
            <span className="functional-model-settings__role-picker-caret" aria-hidden="true" />
          </button>
        </div>

        {roleSettings.error ? (
          <div className="functional-model-settings__error" role="status">
            {roleSettings.error}
          </div>
        ) : null}
      </div>

      {isOpen ? (
        <RolePickerPanel
          activeCategoryId={resolvedCategoryId}
          applying={roleSettings.isSaving}
          categories={visibleCategories}
          filteredRoles={filteredRoles}
          onCategoryChange={setActiveCategoryId}
          onClose={() => setIsOpen(false)}
          onQueryChange={setQuery}
          onRoleSelect={(roleProjectId) => {
            void roleSettings.selectRole(roleProjectId).then((saved) => {
              if (saved) setIsOpen(false);
            });
          }}
          panelRef={panelRef}
          panelStyle={panelStyle}
          query={query}
          roles={visibleRoles}
          selectedRoleProjectId={roleSettings.selectedRoleProjectId}
        />
      ) : null}
    </section>
  );
}
