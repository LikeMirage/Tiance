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
import type { ConversationRoleCatalog } from "../../../entities/role-configuration/model/roleConfiguration";

const PANEL_HEIGHT = 300;

type RoleDefaultPickerProps = {
  label: string;
  catalog: ConversationRoleCatalog;
  selectedRoleProjectId: string;
  disabled: boolean;
  onSelect: (roleId: string) => Promise<boolean>;
};

export function RoleDefaultPicker({ label, catalog, selectedRoleProjectId, disabled, onSelect }: RoleDefaultPickerProps) {
  const { t } = useI18n();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>();
  const [query, setQuery] = useState("");
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);

  const filteredRoles = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return catalog.roles;
    return catalog.roles.filter((role) =>
      `${role.name} ${role.description ?? ""}`
        .toLocaleLowerCase()
        .includes(normalized)
    );
  }, [query, catalog]);
  const visibleCategories = useMemo(
    () => catalog.categories.filter((category) =>
      filteredRoles.some((role) => role.category_id === category.category_id)
    ),
    [filteredRoles, catalog.categories],
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
  const selectedRole = catalog.roles.find(
    (role) => role.role_project_id === selectedRoleProjectId,
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
    <div className="default-role-settings__row">
      <span>{label}</span>
      <button
        ref={triggerRef}
        className="default-role-settings__picker"
        type="button"
        disabled={disabled}
        aria-label={label}
        aria-expanded={isOpen}
        onClick={() => {
          setQuery("");
          setActiveCategoryId(selectedRole?.category_id ?? null);
          setIsOpen((current) => !current);
        }}
      >
        <span>
          {selectedRole?.name ?? t("common.status.unavailable")}
        </span>
        <span className="default-role-settings__caret" aria-hidden="true" />
      </button>
      {isOpen ? (
        <RolePickerPanel
          activeCategoryId={resolvedCategoryId}
          applying={disabled}
          categories={visibleCategories}
          filteredRoles={filteredRoles}
          onCategoryChange={setActiveCategoryId}
          onClose={() => setIsOpen(false)}
          onQueryChange={setQuery}
          onRoleSelect={(roleProjectId) => {
            void onSelect(roleProjectId).then((saved) => {
              if (saved) setIsOpen(false);
            });
          }}
          panelRef={panelRef}
          panelStyle={panelStyle}
          query={query}
          roles={visibleRoles}
          selectedRoleProjectId={selectedRoleProjectId}
        />
      ) : null}
    </div>
  );
}
