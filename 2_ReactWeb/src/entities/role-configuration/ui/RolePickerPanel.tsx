import { createPortal } from "react-dom";
import type { CSSProperties, RefObject } from "react";

import type {
  ConversationRoleCatalogItem,
  ConversationRoleCategory,
} from "../model/roleConfiguration";

import "./role-picker-panel.css";

type Props = {
  activeCategoryId: string | null;
  applying: boolean;
  categories: ConversationRoleCategory[];
  filteredRoles: ConversationRoleCatalogItem[];
  onCategoryChange: (categoryId: string) => void;
  onClose: () => void;
  onQueryChange: (query: string) => void;
  onRoleSelect: (roleProjectId: string) => void;
  panelRef: RefObject<HTMLDivElement | null>;
  panelStyle?: CSSProperties;
  query: string;
  roles: ConversationRoleCatalogItem[];
  selectedRoleProjectId: string | null;
};

export function RolePickerPanel({
  activeCategoryId,
  applying,
  categories,
  filteredRoles,
  onCategoryChange,
  onClose,
  onQueryChange,
  onRoleSelect,
  panelRef,
  panelStyle,
  query,
  roles,
  selectedRoleProjectId,
}: Props) {
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={panelRef}
      className="role-picker-panel"
      role="dialog"
      aria-label="选择角色"
      style={panelStyle}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="role-picker-panel__search-row">
        <input
          autoFocus
          className="role-picker-panel__search"
          type="search"
          value={query}
          placeholder="搜索角色"
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>
      <div className="role-picker-panel__body">
        <div className="role-picker-panel__categories">
          {categories.map((category) => (
            <button
              key={category.category_id}
              className={
                category.category_id === activeCategoryId
                  ? "role-picker-panel__category role-picker-panel__category--active"
                  : "role-picker-panel__category"
              }
              type="button"
              onClick={() => onCategoryChange(category.category_id)}
            >
              <span>{category.name}</span>
              <span>
                {filteredRoles.filter(
                  (role) => role.category_id === category.category_id,
                ).length}
              </span>
            </button>
          ))}
        </div>
        <div className="role-picker-panel__roles">
          {roles.map((role) => (
            <button
              key={role.role_project_id}
              className={
                role.role_project_id === selectedRoleProjectId
                  ? "role-picker-panel__role role-picker-panel__role--selected"
                  : "role-picker-panel__role"
              }
              type="button"
              disabled={applying}
              onClick={() => onRoleSelect(role.role_project_id)}
            >
              <span className="role-picker-panel__role-main">
                <strong>{role.name}</strong>
                {role.description ? <small>{role.description}</small> : null}
              </span>
            </button>
          ))}
          {roles.length === 0 ? (
            <p className="role-picker-panel__empty">没有匹配的角色。</p>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
