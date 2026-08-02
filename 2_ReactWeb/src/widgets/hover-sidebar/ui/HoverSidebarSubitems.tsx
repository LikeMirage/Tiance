import type { Dispatch, RefObject, SetStateAction } from "react";
import { Check } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import type { HoverSidebarSubItem } from "../model/sidebarItems";

export type HoverSidebarContextMenuState = {
  canDelete: boolean;
  kind:
    | "project-category"
    | "knowledge-category"
    | "experience-category"
    | "role-category"
    | "provider-category"
    | "theme-category"
    | "toolset";
  label: string;
  targetId: string;
  x: number;
  y: number;
} | null;

type HoverSidebarSubitemsProps = {
  error?: string | null;
  isOpen: boolean;
  items: HoverSidebarSubItem[];
  kind: "project" | "knowledge" | "experience" | "role" | "provider" | "theme" | "tool";
  onCancelRename?: () => void;
  onCommitRename: (subitem: HoverSidebarSubItem, name: string) => void | Promise<void>;
  onSelect: (subitem: HoverSidebarSubItem) => void;
  renameInputRef: RefObject<HTMLInputElement | null>;
  renamingId: string | null;
  selectedId: string | null;
  setContextMenu: Dispatch<SetStateAction<HoverSidebarContextMenuState>>;
  setRenamingId: Dispatch<SetStateAction<string | null>>;
  state?: "idle" | "loading" | "ready" | "error";
};

export function HoverSidebarSubitems({
  error,
  isOpen,
  items,
  kind,
  onCancelRename,
  onCommitRename,
  onSelect,
  renameInputRef,
  renamingId,
  selectedId,
  setContextMenu,
  setRenamingId,
  state,
}: HoverSidebarSubitemsProps) {
  const { t } = useI18n();
  const isProject = kind === "project";
  const isKnowledge = kind === "knowledge";
  const isExperience = kind === "experience";
  const isRole = kind === "role";
  const isProvider = kind === "provider";
  const isTheme = kind === "theme";
  const isCategory = isProject || isKnowledge || isExperience || isRole || isProvider || isTheme;
  return (
    <div
      className={isOpen
        ? "hover-sidebar__subitems hover-sidebar__subitems--open"
        : "hover-sidebar__subitems"}
      aria-label={
        isProject
          ? t("sidebar.subitems.projectCategories")
          : isRole
            ? t("sidebar.subitems.roleCategories")
            : isTheme
              ? t("sidebar.subitems.themeCategories")
              : t("sidebar.subitems.toolsets")
      }
    >
      {items.map((subitem) => (
        renamingId === subitem.id && !subitem.readonly ? (
          <RenameSubitem
            key={subitem.id}
            inputRef={renameInputRef}
            subitem={subitem}
            onCancel={onCancelRename ?? (() => setRenamingId(null))}
            onCommit={onCommitRename}
          />
        ) : (
          <button
            key={subitem.id}
            className={
              subitem.id === selectedId
                ? "hover-sidebar__subitem hover-sidebar__subitem--active"
                : "hover-sidebar__subitem"
            }
            type="button"
            aria-current={subitem.id === selectedId ? "page" : undefined}
            onMouseDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              event.stopPropagation();
            }}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onSelect(subitem);
            }}
            onContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              if (subitem.readonly) {
                setContextMenu(null);
                return;
              }
              setContextMenu({
                canDelete: true,
                kind: isProject
                  ? "project-category"
                  : isKnowledge
                    ? "knowledge-category"
                    : isExperience
                      ? "experience-category"
                  : isRole
                    ? "role-category"
                    : isProvider
                      ? "provider-category"
                    : isTheme
                      ? "theme-category"
                      : "toolset",
                label: subitem.label,
                targetId: subitem.id,
                x: event.clientX,
                y: event.clientY,
              });
            }}
            onDoubleClick={(event) => {
              event.stopPropagation();
              if (!subitem.readonly) {
                setRenamingId(subitem.id);
              }
            }}
          >
            {subitem.label}
          </button>
        )
      ))}
      {error ? (
        <div className="hover-sidebar__subitem-error" aria-live="polite">
          {error}
        </div>
      ) : isCategory && state !== "loading" && items.length === 0 ? (
        <div className="hover-sidebar__subitem-empty">
          {isRole
            ? t("sidebar.subitems.emptyRoleCategories")
            : isTheme
              ? t("sidebar.subitems.emptyThemeCategories")
              : t("sidebar.subitems.emptyProjectCategories")}
        </div>
      ) : null}
    </div>
  );
}

function RenameSubitem({
  inputRef,
  onCancel,
  onCommit,
  subitem,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  onCancel: () => void;
  onCommit: (subitem: HoverSidebarSubItem, name: string) => void | Promise<void>;
  subitem: HoverSidebarSubItem;
}) {
  const { t } = useI18n();
  return (
    <div className="hover-sidebar__subitem-rename">
      <input
        ref={inputRef}
        className="hover-sidebar__subitem-input"
        defaultValue={subitem.label}
        onBlur={(event) => {
          void onCommit(subitem, event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            void onCommit(subitem, event.currentTarget.value);
          } else if (event.key === "Escape") {
            onCancel();
          }
        }}
      />
      <button
        className="hover-sidebar__subitem-save"
        type="button"
        aria-label={t("sidebar.subitems.saveName")}
        onMouseDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onClick={(event) => {
          event.stopPropagation();
          void onCommit(subitem, inputRef.current?.value ?? subitem.label);
        }}
      >
        <Check className="hover-sidebar__subitem-save-glyph" weight="bold" />
      </button>
    </div>
  );
}
