import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Plus } from "@phosphor-icons/react";

import { ContextMenu, ContextMenuItem, ContextMenuSeparator } from "../../../shared/ui/context-menu";
import { useI18n } from "../../../shared/i18n";
import type { AppThemeControl } from "../../../shared/theme";
import type { UseProjectCatalogResult } from "../../../features/project-catalog/model/useProjectCatalog";
import type { UseToolCatalogResult } from "../../../features/tool-catalog/model/useToolCatalog";
import "./hover-sidebar.css";
import type {
  HoverSidebarSectionId,
  HoverSidebarTransitionDirection,
} from "../model/sidebarSections";
import { primarySidebarItems } from "../model/sidebarItems";
import type { HoverSidebarSubItem } from "../model/sidebarItems";
import { useHoverSidebarRename } from "../model/useHoverSidebarRename";
import { HoverSidebarIcon } from "./hoverSidebarIcons";
import {
  HoverSidebarDeleteModals,
  type HoverSidebarDeleteTarget,
} from "./HoverSidebarDeleteModals";
import {
  HoverSidebarSubitems,
  type HoverSidebarContextMenuState,
} from "./HoverSidebarSubitems";
import { HoverSidebarThemeSelector } from "./HoverSidebarThemeSelector";

type HoverSidebarProjectCatalog = Pick<
  UseProjectCatalogResult,
  | "categories"
  | "clearPendingRenameCategory"
  | "createProjectCategory"
  | "deleteProjectCategory"
  | "error"
  | "isCreatingProjectCategory"
  | "pendingRenameCategoryId"
  | "renameProjectCategory"
  | "selectedCategoryId"
  | "selectCategory"
  | "state"
>;

type HoverSidebarToolCatalog = Pick<
  UseToolCatalogResult,
  | "clearPendingRenameToolset"
  | "createToolset"
  | "deleteToolset"
  | "error"
  | "isCreatingToolset"
  | "items"
  | "pendingRenameToolsetId"
  | "renameToolset"
  | "selectedToolsetId"
  | "selectToolset"
  | "state"
>;

type HoverSidebarThemeCatalog = HoverSidebarProjectCatalog & Pick<
  UseProjectCatalogResult,
  "items"
>;

type HoverSidebarProps = {
  activeSection: HoverSidebarSectionId;
  onSelectSection: (
    sectionId: HoverSidebarSectionId,
    direction: HoverSidebarTransitionDirection,
    explicitCatalogItemId?: string,
  ) => void;
  projectCatalog: HoverSidebarProjectCatalog;
  knowledgeCatalog: HoverSidebarProjectCatalog;
  experienceCatalog: HoverSidebarProjectCatalog;
  roleCatalog: HoverSidebarProjectCatalog;
  providerCatalog: HoverSidebarProjectCatalog;
  themeCatalog: HoverSidebarThemeCatalog;
  themeControl: AppThemeControl;
  toolCatalog: HoverSidebarToolCatalog;
};

export const HoverSidebar = memo(function HoverSidebar({
  activeSection,
  onSelectSection,
  projectCatalog,
  knowledgeCatalog,
  experienceCatalog,
  roleCatalog,
  providerCatalog,
  themeCatalog,
  themeControl,
  toolCatalog,
}: HoverSidebarProps) {
  const { t } = useI18n();
  const [isExpanded, setIsExpanded] = useState(false);
  const [hoveredCatalogSection, setHoveredCatalogSection] =
    useState<HoverSidebarSectionId | null>(null);
  const [contextMenu, setContextMenu] = useState<HoverSidebarContextMenuState>(null);
  const [pendingDeleteProjectCategory, setPendingDeleteProjectCategory] =
    useState<HoverSidebarDeleteTarget>(null);
  const [pendingDeleteToolset, setPendingDeleteToolset] =
    useState<HoverSidebarDeleteTarget>(null);
  const [deletingProjectCategoryId, setDeletingProjectCategoryId] = useState<string | null>(null);
  const [deletingToolsetId, setDeletingToolsetId] = useState<string | null>(null);
  const sidebarInnerRef = useRef<HTMLDivElement>(null);
  const delayedActionTimersRef = useRef<number[]>([]);
  const projectRename = useHoverSidebarRename({
    clearPendingRename: projectCatalog.clearPendingRenameCategory,
    pendingRenameId: projectCatalog.pendingRenameCategoryId,
    renameItem: projectCatalog.renameProjectCategory,
  });
  const knowledgeRename = useHoverSidebarRename({
    clearPendingRename: knowledgeCatalog.clearPendingRenameCategory,
    pendingRenameId: knowledgeCatalog.pendingRenameCategoryId,
    renameItem: knowledgeCatalog.renameProjectCategory,
  });
  const experienceRename = useHoverSidebarRename({
    clearPendingRename: experienceCatalog.clearPendingRenameCategory,
    pendingRenameId: experienceCatalog.pendingRenameCategoryId,
    renameItem: experienceCatalog.renameProjectCategory,
  });
  const roleRename = useHoverSidebarRename({
    clearPendingRename: roleCatalog.clearPendingRenameCategory,
    pendingRenameId: roleCatalog.pendingRenameCategoryId,
    renameItem: roleCatalog.renameProjectCategory,
  });
  const providerRename = useHoverSidebarRename({
    clearPendingRename: providerCatalog.clearPendingRenameCategory,
    pendingRenameId: providerCatalog.pendingRenameCategoryId,
    renameItem: providerCatalog.renameProjectCategory,
  });
  const themeRename = useHoverSidebarRename({
    clearPendingRename: themeCatalog.clearPendingRenameCategory,
    pendingRenameId: themeCatalog.pendingRenameCategoryId,
    renameItem: themeCatalog.renameProjectCategory,
  });
  const toolRename = useHoverSidebarRename({
    clearPendingRename: toolCatalog.clearPendingRenameToolset,
    pendingRenameId: toolCatalog.pendingRenameToolsetId,
    renameItem: toolCatalog.renameToolset,
  });
  const projectSidebarItems = useMemo(
    () => projectCatalog.categories.length > 0
      ? projectCatalog.categories.map((category) => ({
          id: category.category_id,
          isDefault: category.is_default,
          label: category.name,
          sectionId: "overview" as const,
        }))
      : [],
    [projectCatalog.categories, projectCatalog.state],
  );
  const knowledgeSidebarItems = useMemo(
    () => knowledgeCatalog.categories.map((category) => ({
      id: category.category_id,
      isDefault: category.is_default,
      label: category.name,
      sectionId: "knowledge" as const,
    })),
    [knowledgeCatalog.categories, knowledgeCatalog.state],
  );
  const experienceSidebarItems = useMemo(
    () => experienceCatalog.categories.map((category) => ({
      id: category.category_id,
      isDefault: category.is_default,
      label: category.name,
      sectionId: "experience" as const,
    })),
    [experienceCatalog.categories, experienceCatalog.state],
  );
  const toolSidebarItems = useMemo(
    () => toolCatalog.items.length > 0
      ? toolCatalog.items.map((toolset) => ({
          id: toolset.category_id,
          label: toolset.name,
          readonly: toolset.readonly,
          sectionId: "tools" as const,
        }))
      : [],
    [toolCatalog.items],
  );
  const roleSidebarItems = useMemo(
    () => roleCatalog.categories.length > 0
      ? roleCatalog.categories.map((category) => ({
          id: category.category_id,
          isDefault: category.is_default,
          label: category.name,
          sectionId: "roles" as const,
        }))
      : [],
    [roleCatalog.categories, roleCatalog.state],
  );
  const providerSidebarItems = useMemo(
    () => providerCatalog.categories.map((category) => ({
      id: category.category_id,
      isDefault: category.is_default,
      label: category.name,
      sectionId: "models" as const,
    })),
    [providerCatalog.categories, providerCatalog.state],
  );
  const themeSidebarItems = useMemo(
    () => themeCatalog.categories.map((category) => ({
      id: category.category_id,
      isDefault: category.is_default,
      label: category.name,
      sectionId: "themes" as const,
    })),
    [themeCatalog.categories, themeCatalog.state],
  );
  const activeProjectSubItem =
    projectSidebarItems.find((subitem) => subitem.id === projectCatalog.selectedCategoryId) ??
    projectSidebarItems[0];
  const activeToolSubItem =
    toolSidebarItems.find((subitem) => subitem.id === toolCatalog.selectedToolsetId) ??
    toolSidebarItems[0];
  const activeRoleSubItem =
    roleSidebarItems.find((subitem) => subitem.id === roleCatalog.selectedCategoryId) ??
    roleSidebarItems[0];
  const activeThemeSubItem =
    themeSidebarItems.find((subitem) => subitem.id === themeCatalog.selectedCategoryId) ??
    themeSidebarItems[0];
  const isProjectGroupOpen = activeSection === "overview" || hoveredCatalogSection === "overview";
  const isKnowledgeGroupOpen =
    activeSection === "knowledge" || hoveredCatalogSection === "knowledge";
  const isExperienceGroupOpen =
    activeSection === "experience" || hoveredCatalogSection === "experience";
  const isRoleGroupOpen = activeSection === "roles" || hoveredCatalogSection === "roles";
  const isProviderGroupOpen = activeSection === "models" || hoveredCatalogSection === "models";
  const isThemeGroupOpen = activeSection === "themes" || hoveredCatalogSection === "themes";
  const isToolGroupOpen = activeSection === "tools" || hoveredCatalogSection === "tools";
  const isSidebarExpanded = isExpanded;

  const scheduleDelayedSidebarAction = (action: () => void) => {
    const timer = window.setTimeout(() => {
      delayedActionTimersRef.current = delayedActionTimersRef.current.filter(
        (item) => item !== timer,
      );
      action();
    }, 0);
    delayedActionTimersRef.current.push(timer);
  };

  useEffect(() => () => {
    delayedActionTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    delayedActionTimersRef.current = [];
  }, []);

  useEffect(() => {
    setContextMenu(null);
  }, [
    activeSection,
    projectCatalog.selectedCategoryId,
    knowledgeCatalog.selectedCategoryId,
    experienceCatalog.selectedCategoryId,
    roleCatalog.selectedCategoryId,
    providerCatalog.selectedCategoryId,
    themeCatalog.selectedCategoryId,
    toolCatalog.selectedToolsetId,
  ]);

  useEffect(() => {
    if (!isExpanded) {
      setContextMenu(null);
    }
  }, [isExpanded]);

  const handleSectionClick = (
    sectionId: HoverSidebarSectionId,
    explicitCatalogItemId?: string,
  ) => {
    const currentIndex = primarySidebarItems.findIndex((item) => item.id === activeSection);
    const nextIndex = primarySidebarItems.findIndex((item) => item.id === sectionId);
    onSelectSection(
      sectionId,
      nextIndex < currentIndex ? "up" : "down",
      explicitCatalogItemId,
    );
  };

  const handlePrimaryItemClick = (sectionId: HoverSidebarSectionId) => {
    handleSectionClick(sectionId);
  };

  const handleCatalogSubItemClick = (
    sectionId: HoverSidebarSectionId,
    selectItem: (itemId: string) => void,
    subitem: HoverSidebarSubItem | undefined,
  ) => {
    setContextMenu(null);
    if (subitem && sectionId === activeSection) {
      selectItem(subitem.id);
      return;
    }
    handleSectionClick(sectionId, subitem?.id);
  };

  const handleCreateCatalogItem = (
    sectionId: HoverSidebarSectionId,
    createItem: () => Promise<unknown>,
  ) => {
    setContextMenu(null);
    handleSectionClick(sectionId);
    void createItem().catch(() => undefined);
  };

  const handleContextMenuRename = () => {
    if (!contextMenu) return;
    const renameController = contextMenu.kind === "project-category"
      ? projectRename
      : contextMenu.kind === "knowledge-category"
        ? knowledgeRename
      : contextMenu.kind === "experience-category"
          ? experienceRename
      : contextMenu.kind === "role-category"
        ? roleRename
        : contextMenu.kind === "provider-category"
          ? providerRename
        : contextMenu.kind === "theme-category"
          ? themeRename
          : toolRename;
    renameController.setRenamingId(contextMenu.targetId);
    setContextMenu(null);
  };

  const handleContextMenuDelete = () => {
    if (!contextMenu || !contextMenu.canDelete) return;
    if (
      contextMenu.kind === "project-category"
      || contextMenu.kind === "knowledge-category"
      || contextMenu.kind === "experience-category"
      || contextMenu.kind === "role-category"
      || contextMenu.kind === "provider-category"
      || contextMenu.kind === "theme-category"
    ) {
      setPendingDeleteProjectCategory({
        id: contextMenu.targetId,
        kind: contextMenu.kind === "role-category"
          ? "role"
          : contextMenu.kind === "provider-category"
            ? "provider"
          : contextMenu.kind === "theme-category"
            ? "theme"
            : "project",
        label: contextMenu.label,
      });
    } else {
      setPendingDeleteToolset({
        id: contextMenu.targetId,
        label: contextMenu.label,
      });
    }
    setContextMenu(null);
  };

  const shouldKeepSidebarForContextMenu = (target: EventTarget | null) =>
    contextMenu !== null || isHoverSidebarContextMenuTarget(target);

  const handleCatalogGroupPointerLeave = (
    sectionId: HoverSidebarSectionId,
    event: ReactPointerEvent<HTMLElement>,
  ) => {
    if (shouldKeepSidebarForContextMenu(event.relatedTarget)) return;
    setHoveredCatalogSection((current) => current === sectionId ? null : current);
  };

  const handleSidebarPointerLeave = (event: ReactPointerEvent<HTMLElement>) => {
    if (shouldKeepSidebarForContextMenu(event.relatedTarget)) return;
    setIsExpanded(false);
    setContextMenu(null);
  };

  const handleContextMenuClose = () => {
    setContextMenu(null);
    scheduleDelayedSidebarAction(() => {
      if (sidebarInnerRef.current?.matches(":hover")) return;
      setIsExpanded(false);
      setHoveredCatalogSection(null);
    });
  };

  return (
    <aside
      className={[
        "hover-sidebar",
        isSidebarExpanded ? "hover-sidebar--expanded" : "",
      ].filter(Boolean).join(" ")}
      aria-label={t("sidebar.aria.primary")}
    >
      <div
        ref={sidebarInnerRef}
        className="hover-sidebar__inner"
        onPointerEnter={() => setIsExpanded(true)}
        onPointerLeave={handleSidebarPointerLeave}
      >
        <nav className="hover-sidebar__nav" aria-label={t("sidebar.aria.workspaceSections")}>
          {primarySidebarItems.map((item) => (
            <div
              className={
                isSidebarItemGroupOpen(
                  item.id,
                  isProjectGroupOpen,
                  isKnowledgeGroupOpen,
                  isExperienceGroupOpen,
                  isRoleGroupOpen,
                  isProviderGroupOpen,
                  isThemeGroupOpen,
                  isToolGroupOpen,
                )
                  ? "hover-sidebar__item-group hover-sidebar__item-group--open"
                  : "hover-sidebar__item-group"
              }
              key={item.id}
              onPointerEnter={isCatalogSection(item.id)
                ? () => setHoveredCatalogSection(item.id)
                : undefined}
              onPointerLeave={isCatalogSection(item.id)
                ? (event) => handleCatalogGroupPointerLeave(item.id, event)
                : undefined}
            >
              <div
                className={
                  hasSidebarItemAction(item.id)
                    ? "hover-sidebar__item-row hover-sidebar__item-row--with-action"
                    : "hover-sidebar__item-row"
                }
              >
                <button
                  className={
                    activeSection === item.id
                      ? "hover-sidebar__item hover-sidebar__item--active"
                      : "hover-sidebar__item"
                  }
                  type="button"
                  onClick={() => handlePrimaryItemClick(item.id as HoverSidebarSectionId)}
                >
                  <span className="hover-sidebar__item-icon" aria-hidden="true">
                    <HoverSidebarIcon iconKey={item.iconKey} />
                  </span>
                  <span className="hover-sidebar__item-copy">
                    <span className="hover-sidebar__item-label">{t(item.labelKey)}</span>
                  </span>
                </button>
                {item.id === "overview" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addProjectCategory")}
                    disabled={projectCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem("overview", projectCatalog.createProjectCategory);
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "knowledge" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addProjectCategory")}
                    disabled={knowledgeCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem(
                        "knowledge",
                        knowledgeCatalog.createProjectCategory,
                      );
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "experience" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addProjectCategory")}
                    disabled={experienceCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem(
                        "experience",
                        experienceCatalog.createProjectCategory,
                      );
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "roles" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addRoleCategory")}
                    disabled={roleCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem("roles", roleCatalog.createProjectCategory);
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "themes" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addThemeCategory")}
                    disabled={themeCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem("themes", themeCatalog.createProjectCategory);
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "models" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addProjectCategory")}
                    disabled={providerCatalog.isCreatingProjectCategory}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem(
                        "models",
                        providerCatalog.createProjectCategory,
                      );
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : item.id === "tools" ? (
                  <button
                    className="hover-sidebar__item-action"
                    type="button"
                    aria-label={t("sidebar.subitems.addToolset")}
                    disabled={toolCatalog.isCreatingToolset}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateCatalogItem("tools", toolCatalog.createToolset);
                    }}
                  >
                    <Plus
                      className="hover-sidebar__item-action-glyph"
                      weight="bold"
                      aria-hidden="true"
                    />
                  </button>
                ) : null}
              </div>
              {item.id === "overview" ? (
                <HoverSidebarSubitems
                  error={projectCatalog.error}
                  isOpen={isProjectGroupOpen}
                  items={projectSidebarItems}
                  kind="project"
                  onCancelRename={projectRename.cancelRename}
                  onCommitRename={projectRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "overview",
                    projectCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={projectRename.inputRef}
                  renamingId={projectRename.renamingId}
                  selectedId={projectCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={projectRename.setRenamingId}
                  state={projectCatalog.state}
                />
              ) : item.id === "knowledge" ? (
                <HoverSidebarSubitems
                  error={knowledgeCatalog.error}
                  isOpen={isKnowledgeGroupOpen}
                  items={knowledgeSidebarItems}
                  kind="knowledge"
                  onCancelRename={knowledgeRename.cancelRename}
                  onCommitRename={knowledgeRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "knowledge",
                    knowledgeCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={knowledgeRename.inputRef}
                  renamingId={knowledgeRename.renamingId}
                  selectedId={knowledgeCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={knowledgeRename.setRenamingId}
                  state={knowledgeCatalog.state}
                />
              ) : item.id === "experience" ? (
                <HoverSidebarSubitems
                  error={experienceCatalog.error}
                  isOpen={isExperienceGroupOpen}
                  items={experienceSidebarItems}
                  kind="experience"
                  onCancelRename={experienceRename.cancelRename}
                  onCommitRename={experienceRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "experience",
                    experienceCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={experienceRename.inputRef}
                  renamingId={experienceRename.renamingId}
                  selectedId={experienceCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={experienceRename.setRenamingId}
                  state={experienceCatalog.state}
                />
              ) : item.id === "roles" ? (
                <HoverSidebarSubitems
                  error={roleCatalog.error}
                  isOpen={isRoleGroupOpen}
                  items={roleSidebarItems}
                  kind="role"
                  onCancelRename={roleRename.cancelRename}
                  onCommitRename={roleRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "roles",
                    roleCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={roleRename.inputRef}
                  renamingId={roleRename.renamingId}
                  selectedId={roleCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={roleRename.setRenamingId}
                  state={roleCatalog.state}
                />
              ) : item.id === "themes" ? (
                <HoverSidebarSubitems
                  error={themeCatalog.error}
                  isOpen={isThemeGroupOpen}
                  items={themeSidebarItems}
                  kind="theme"
                  onCancelRename={themeRename.cancelRename}
                  onCommitRename={themeRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "themes",
                    themeCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={themeRename.inputRef}
                  renamingId={themeRename.renamingId}
                  selectedId={activeThemeSubItem?.id ?? themeCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={themeRename.setRenamingId}
                  state={themeCatalog.state}
                />
              ) : item.id === "models" ? (
                <HoverSidebarSubitems
                  error={providerCatalog.error}
                  isOpen={isProviderGroupOpen}
                  items={providerSidebarItems}
                  kind="provider"
                  onCancelRename={providerRename.cancelRename}
                  onCommitRename={providerRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "models",
                    providerCatalog.selectCategory,
                    subitem,
                  )}
                  renameInputRef={providerRename.inputRef}
                  renamingId={providerRename.renamingId}
                  selectedId={providerCatalog.selectedCategoryId}
                  setContextMenu={setContextMenu}
                  setRenamingId={providerRename.setRenamingId}
                  state={providerCatalog.state}
                />
              ) : item.id === "tools" ? (
                <HoverSidebarSubitems
                  error={toolCatalog.error}
                  isOpen={isToolGroupOpen}
                  items={toolSidebarItems}
                  kind="tool"
                  onCancelRename={toolRename.cancelRename}
                  onCommitRename={toolRename.commitRename}
                  onSelect={(subitem) => handleCatalogSubItemClick(
                    "tools",
                    toolCatalog.selectToolset,
                    subitem,
                  )}
                  renameInputRef={toolRename.inputRef}
                  renamingId={toolRename.renamingId}
                  selectedId={toolCatalog.selectedToolsetId}
                  setContextMenu={setContextMenu}
                  setRenamingId={toolRename.setRenamingId}
                />
              ) : null}
            </div>
          ))}
        </nav>

        <div className="hover-sidebar__spacer" />

        <div className="hover-sidebar__footer">
          <HoverSidebarThemeSelector
            categories={themeCatalog.categories}
            isSidebarExpanded={isSidebarExpanded}
            themeProjects={themeCatalog.items}
            themeControl={themeControl}
          />
        </div>
      </div>

      {contextMenu ? (
        <HoverSidebarContextMenu
          menu={contextMenu}
          onClose={handleContextMenuClose}
          onDelete={handleContextMenuDelete}
          onRename={handleContextMenuRename}
        />
      ) : null}

        <HoverSidebarDeleteModals
        deleteProjectCategory={projectCatalog.deleteProjectCategory}
        deleteToolset={toolCatalog.deleteToolset}
        deletingProjectCategoryId={deletingProjectCategoryId}
        deletingToolsetId={deletingToolsetId}
        pendingDeleteProjectCategory={pendingDeleteProjectCategory}
        pendingDeleteToolset={pendingDeleteToolset}
        setDeletingProjectCategoryId={setDeletingProjectCategoryId}
        setDeletingToolsetId={setDeletingToolsetId}
        setPendingDeleteProjectCategory={setPendingDeleteProjectCategory}
          setPendingDeleteToolset={setPendingDeleteToolset}
        />
    </aside>
  );
});

function HoverSidebarContextMenu({
  menu,
  onClose,
  onDelete,
  onRename,
}: {
  menu: NonNullable<HoverSidebarContextMenuState>;
  onClose: () => void;
  onDelete: () => void;
  onRename: () => void;
}) {
  const { t } = useI18n();
  return (
    <ContextMenu
      onClose={onClose}
      position={{ x: menu.x, y: menu.y }}
    >
      <ContextMenuItem onSelect={onRename}>
        {t("common.actions.rename")}
      </ContextMenuItem>
      {menu.canDelete ? (
        <>
          <ContextMenuSeparator />
          <ContextMenuItem danger onSelect={onDelete}>
            {t("common.actions.delete")}
          </ContextMenuItem>
        </>
      ) : null}
    </ContextMenu>
  );
}

function isSidebarItemGroupOpen(
  itemId: HoverSidebarSectionId,
  isProjectGroupOpen: boolean,
  isKnowledgeGroupOpen: boolean,
  isExperienceGroupOpen: boolean,
  isRoleGroupOpen: boolean,
  isProviderGroupOpen: boolean,
  isThemeGroupOpen: boolean,
  isToolGroupOpen: boolean,
) {
  if (itemId === "overview") return isProjectGroupOpen;
  if (itemId === "knowledge") return isKnowledgeGroupOpen;
  if (itemId === "experience") return isExperienceGroupOpen;
  if (itemId === "roles") return isRoleGroupOpen;
  if (itemId === "models") return isProviderGroupOpen;
  if (itemId === "themes") return isThemeGroupOpen;
  if (itemId === "tools") return isToolGroupOpen;
  return false;
}

function hasSidebarItemAction(itemId: HoverSidebarSectionId) {
  return itemId === "overview"
    || itemId === "knowledge"
    || itemId === "experience"
    || itemId === "roles"
    || itemId === "models"
    || itemId === "themes"
    || itemId === "tools";
}

function isCatalogSection(
  sectionId: HoverSidebarSectionId,
): sectionId is "overview" | "knowledge" | "experience" | "roles" | "models" | "themes" | "tools" {
  return sectionId === "overview"
    || sectionId === "knowledge"
    || sectionId === "experience"
    || sectionId === "roles"
    || sectionId === "models"
    || sectionId === "themes"
    || sectionId === "tools";
}

function isHoverSidebarContextMenuTarget(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest(".ds-context-menu, .ds-context-menu__dismiss-layer"))
  );
}
