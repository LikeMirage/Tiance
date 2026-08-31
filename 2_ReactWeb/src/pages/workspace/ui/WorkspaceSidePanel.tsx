import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { CaretRight } from "@phosphor-icons/react";

import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import {
  functionalModelSettingsSections,
  type FunctionalModelSettingsSectionId,
} from "../../../features/functional-model-settings/model/functionalModelSections";
import type { UseProviderCatalogResult } from "../../../features/provider-catalog/model/useProviderCatalog";
import type { UseToolFoldersResult } from "../../../features/tool-catalog/model/useToolFolders";
import type { UseToolFolderBrowserResult } from "../../../features/tool-browser/model/toolBrowserTypes";
import type { ProjectFileDragData } from "../../../entities/project/model/projectFileDragData";
import type {
  HoverSidebarSectionId,
  HoverSidebarTransitionDirection,
} from "../../../widgets/hover-sidebar/model/sidebarSections";
import {
  isFunctionalModelSettingsSection,
  type WorkspaceSettingsSectionId,
} from "../model/workspaceSettingsSections";
import { ProviderCatalogPanel } from "../../../features/provider-catalog/ui/ProviderCatalogPanel";
import { useI18n } from "../../../shared/i18n";
import {
  ToolCatalogPanel,
  type ToolCatalogPanelToolCatalog,
} from "../../../features/tool-catalog/ui/ToolCatalogPanel";
import {
  WorkspaceProjectsPanel,
  type WorkspaceProjectsPanelProjectCatalog,
} from "./WorkspaceProjectsPanel";
import "./workspace-side-panel.css";

type WorkspaceSidePanelProps = {
  activeSection: HoverSidebarSectionId;
  activeSettingsSectionId: WorkspaceSettingsSectionId;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  projectCatalog: WorkspaceProjectsPanelProjectCatalog;
  knowledgeProjectCatalog: WorkspaceProjectsPanelProjectCatalog;
  experienceProjectCatalog: WorkspaceProjectsPanelProjectCatalog;
  roleProjectCatalog: WorkspaceProjectsPanelProjectCatalog;
  themeProjectCatalog: WorkspaceProjectsPanelProjectCatalog;
  providerProjectCatalog: WorkspaceProjectsPanelProjectCatalog;
  providerCatalog: UseProviderCatalogResult;
  onOpenProvider: (providerId: string) => void;
  toolCatalog: ToolCatalogPanelToolCatalog;
  toolBrowser: UseToolFolderBrowserResult;
  toolDocumentTabs: ReturnType<typeof useDocumentTabs>;
  toolFolders: UseToolFoldersResult;
  isFunctionalModelGroupOpen: boolean;
  sidePanelWidth: number;
  transitionDirection: HoverSidebarTransitionDirection;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  onSelectFunctionalModelSection: (sectionId: FunctionalModelSettingsSectionId) => void;
  onSelectGithubSettings: () => void;
  onSelectGlobalMemorySettings: () => void;
  onSelectLanguageSettings: () => void;
  onSelectSoftwareUpdateSettings: () => void;
  onSelectAnnouncementSettings: () => void;
  onSelectNetworkSettings: () => void;
  onSelectAccessManagementSettings: () => void;
  onSelectAccessSecuritySettings: () => void;
  onSelectTokenEstimationSettings: () => void;
  onToggleFunctionalModelGroup: () => void;
};

type SidePanelTransitionState = {
  direction: HoverSidebarTransitionDirection;
};

const WORKSPACE_SIDE_PANEL_SECTIONS: readonly HoverSidebarSectionId[] = [
  "overview",
  "knowledge",
  "experience",
  "roles",
  "themes",
  "models",
  "tools",
  "settings",
];

export const WorkspaceSidePanel = memo(function WorkspaceSidePanel({
  activeSection,
  activeSettingsSectionId,
  documentTabs,
  projectCatalog,
  knowledgeProjectCatalog,
  experienceProjectCatalog,
  roleProjectCatalog,
  themeProjectCatalog,
  providerProjectCatalog,
  providerCatalog,
  onOpenProvider,
  toolCatalog,
  toolBrowser,
  toolDocumentTabs,
  toolFolders,
  isFunctionalModelGroupOpen,
  sidePanelWidth,
  transitionDirection,
  onReferenceProjectFile,
  onSelectFunctionalModelSection,
  onSelectGithubSettings,
  onSelectGlobalMemorySettings,
  onSelectLanguageSettings,
  onSelectSoftwareUpdateSettings,
  onSelectAnnouncementSettings,
  onSelectNetworkSettings,
  onSelectAccessManagementSettings,
  onSelectAccessSecuritySettings,
  onSelectTokenEstimationSettings,
  onToggleFunctionalModelGroup,
}: WorkspaceSidePanelProps) {
  const { t } = useI18n();
  const previousSectionRef = useRef(activeSection);
  const transitionTimerRef = useRef<number | null>(null);
  const [settingsSearchKeyword, setSettingsSearchKeyword] = useState("");
  const [transitionState, setTransitionState] = useState<SidePanelTransitionState | null>(null);
  const [visitedSections, setVisitedSections] = useState<ReadonlySet<HoverSidebarSectionId>>(
    () => new Set<HoverSidebarSectionId>(["overview"]),
  );
  const normalizedSettingsSearchKeyword = normalizeSettingsSearchText(settingsSearchKeyword);
  const isSearchingSettings = normalizedSettingsSearchKeyword.length > 0;
  const isTokenEstimationSettingsActive =
    activeSettingsSectionId === "token-estimation";
  const isLanguageSettingsActive = activeSettingsSectionId === "language";
  const isSoftwareUpdateSettingsActive = activeSettingsSectionId === "software-update";
  const isAnnouncementSettingsActive = activeSettingsSectionId === "announcements";
  const isGithubSettingsActive = activeSettingsSectionId === "github";
  const isGlobalMemorySettingsActive = activeSettingsSectionId === "global-memory";
  const isNetworkSettingsActive = activeSettingsSectionId === "network";
  const isAccessManagementSettingsActive = activeSettingsSectionId === "access-management";
  const isAccessSecuritySettingsActive = activeSettingsSectionId === "access-security";
  const isFunctionalModelGroupActive =
    isFunctionalModelSettingsSection(activeSettingsSectionId);
  const shouldShowTokenEstimationSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.tokenEstimation")} token usage estimate`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowNetworkSettingsSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.network")} proxy timeout port github`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowAccessManagementSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.accessManagement")} remote external wechat dingtalk telegram 外部访问 微信 钉钉`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowAccessSecuritySearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(`${t("workspace.settings.accessSecurity")} 密码 登录 会话 security password login`)
      .includes(normalizedSettingsSearchKeyword);
  const shouldShowLanguageSettingsSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.language")} language locale 语言 язык`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowSoftwareUpdateSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.softwareUpdate")} update version release`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowGithubSettingsSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.github")} github login repository private`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowAnnouncementSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.announcements")} announcement notice 公告 通知`,
    ).includes(normalizedSettingsSearchKeyword);
  const shouldShowGlobalMemorySettingsSearchResult =
    !isSearchingSettings
    || normalizeSettingsSearchText(
      `${t("workspace.settings.globalMemory")} memory long-term history deleted 全局记忆 长期记忆`,
    ).includes(normalizedSettingsSearchKeyword);
  const filteredFunctionalModelSections = useMemo(
    () =>
      isSearchingSettings
        ? functionalModelSettingsSections.filter((section) =>
            normalizeSettingsSearchText(
              `${t("workspace.settings.functionalModel")} ${t(section.labelKey)} ${section.id}`,
            ).includes(normalizedSettingsSearchKeyword),
          )
        : functionalModelSettingsSections,
    [isSearchingSettings, normalizedSettingsSearchKeyword, t],
  );

  useLayoutEffect(() => {
    if (previousSectionRef.current === activeSection) {
      return;
    }

    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
    }

    setTransitionState({ direction: transitionDirection });
    previousSectionRef.current = activeSection;

    transitionTimerRef.current = window.setTimeout(() => {
      setTransitionState(null);
      transitionTimerRef.current = null;
    }, 320);

    return () => {
      if (transitionTimerRef.current !== null) {
        window.clearTimeout(transitionTimerRef.current);
        transitionTimerRef.current = null;
      }
    };
  }, [activeSection, transitionDirection]);

  useEffect(() => {
    setVisitedSections((current) => {
      if (current.has(activeSection)) {
        return current;
      }
      return new Set([...current, activeSection]);
    });
  }, [activeSection]);

  const renderSettingsPanel = () => (
    <aside className="workspace-settings-panel" aria-label={t("workspace.settings.panel")}>
      <header className="workspace-settings-panel__header">
        <h2 className="workspace-settings-panel__title">{t("workspace.settings.title")}</h2>
      </header>
      <label className="workspace-settings-panel__search">
        <span className="workspace-settings-panel__search-label">{t("workspace.settings.search")}</span>
        <input
          className="workspace-settings-panel__search-input"
          type="search"
          value={settingsSearchKeyword}
          placeholder={t("workspace.settings.search")}
          onChange={(event) => setSettingsSearchKeyword(event.target.value)}
        />
      </label>
      <nav className="workspace-settings-panel__list" aria-label={t("workspace.settings.categories")}>
        {isSearchingSettings ? (
          <div className="workspace-settings-panel__search-results">
            {shouldShowSoftwareUpdateSearchResult ? (
              <button
                className={isSoftwareUpdateSettingsActive
                  ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                  : "workspace-settings-panel__search-result"}
                type="button"
                aria-current={isSoftwareUpdateSettingsActive ? "page" : undefined}
                onClick={onSelectSoftwareUpdateSettings}
              >
                <span className="workspace-settings-panel__search-result-title">{t("workspace.settings.softwareUpdate")}</span>
                <span className="workspace-settings-panel__search-result-meta">{t("softwareUpdate.check")}</span>
              </button>
            ) : null}
            {shouldShowLanguageSettingsSearchResult ? (
              <button
                className={
                  isLanguageSettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isLanguageSettingsActive ? "page" : undefined}
                onClick={onSelectLanguageSettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.language")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("languageSettings.selection")}
                </span>
              </button>
            ) : null}
            {shouldShowNetworkSettingsSearchResult ? (
              <button
                className={
                  isNetworkSettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isNetworkSettingsActive ? "page" : undefined}
                onClick={onSelectNetworkSettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.network")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("workspace.settings.connection")}
                </span>
              </button>
            ) : null}
            {shouldShowAccessManagementSearchResult ? (
              <button
                className={
                  isAccessManagementSettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isAccessManagementSettingsActive ? "page" : undefined}
                onClick={onSelectAccessManagementSettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.accessManagement")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("accessManagement.tabs.external")}
                </span>
              </button>
            ) : null}
            {shouldShowAccessSecuritySearchResult ? (
              <button
                className={isAccessSecuritySettingsActive
                  ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                  : "workspace-settings-panel__search-result"}
                type="button"
                aria-current={isAccessSecuritySettingsActive ? "page" : undefined}
                onClick={onSelectAccessSecuritySettings}
              >
                <span className="workspace-settings-panel__search-result-title">安全设置</span>
                <span className="workspace-settings-panel__search-result-meta">密码与登录会话</span>
              </button>
            ) : null}
            {shouldShowGithubSettingsSearchResult ? (
              <button
                className={
                  isGithubSettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isGithubSettingsActive ? "page" : undefined}
                onClick={onSelectGithubSettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.github")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("githubSettings.login.title")}
                </span>
              </button>
            ) : null}
            {shouldShowAnnouncementSearchResult ? (
              <button
                className={isAnnouncementSettingsActive
                  ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                  : "workspace-settings-panel__search-result"}
                type="button"
                aria-current={isAnnouncementSettingsActive ? "page" : undefined}
                onClick={onSelectAnnouncementSettings}
              >
                <span className="workspace-settings-panel__search-result-title">{t("workspace.settings.announcements")}</span>
                <span className="workspace-settings-panel__search-result-meta">{t("announcements.history")}</span>
              </button>
            ) : null}
            {shouldShowGlobalMemorySettingsSearchResult ? (
              <button
                className={
                  isGlobalMemorySettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isGlobalMemorySettingsActive ? "page" : undefined}
                onClick={onSelectGlobalMemorySettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.globalMemory")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("globalMemoryManager.eventLog")}
                </span>
              </button>
            ) : null}
            {shouldShowTokenEstimationSearchResult ? (
              <button
                className={
                  isTokenEstimationSettingsActive
                    ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                    : "workspace-settings-panel__search-result"
                }
                type="button"
                aria-current={isTokenEstimationSettingsActive ? "page" : undefined}
                onClick={onSelectTokenEstimationSettings}
              >
                <span className="workspace-settings-panel__search-result-title">
                  {t("workspace.settings.tokenEstimation")}
                </span>
                <span className="workspace-settings-panel__search-result-meta">
                  {t("workspace.settings.usage")}
                </span>
              </button>
            ) : null}
            {filteredFunctionalModelSections.length > 0 ? (
              filteredFunctionalModelSections.map((section) => (
                <button
                  key={section.id}
                  className={
                    activeSettingsSectionId === section.id
                      ? "workspace-settings-panel__search-result workspace-settings-panel__search-result--active"
                      : "workspace-settings-panel__search-result"
                  }
                  type="button"
                  aria-current={
                    activeSettingsSectionId === section.id
                      ? "page"
                      : undefined
                  }
                  onClick={() => onSelectFunctionalModelSection(section.id)}
                >
                  <span className="workspace-settings-panel__search-result-title">
                    {t(section.labelKey)}
                  </span>
                  <span className="workspace-settings-panel__search-result-meta">
                    {t("workspace.settings.functionalModel")}
                  </span>
                </button>
              ))
            ) : null}
            {!shouldShowSoftwareUpdateSearchResult
              && !shouldShowAnnouncementSearchResult
              && !shouldShowLanguageSettingsSearchResult
              && !shouldShowGithubSettingsSearchResult
              && !shouldShowGlobalMemorySettingsSearchResult
              && !shouldShowNetworkSettingsSearchResult
              && !shouldShowAccessManagementSearchResult
              && !shouldShowAccessSecuritySearchResult
              && !shouldShowTokenEstimationSearchResult
              && filteredFunctionalModelSections.length === 0 ? (
              <div className="workspace-settings-panel__empty" role="status">
                {t("workspace.settings.noMatches")}
              </div>
            ) : null}
          </div>
        ) : (
          <>
            <button
              className={isSoftwareUpdateSettingsActive
                ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                : "workspace-settings-panel__standalone"}
              type="button"
              aria-current={isSoftwareUpdateSettingsActive ? "page" : undefined}
              onClick={onSelectSoftwareUpdateSettings}
            >
              {t("workspace.settings.softwareUpdate")}
            </button>
            <button
              className={isAnnouncementSettingsActive
                ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                : "workspace-settings-panel__standalone"}
              type="button"
              aria-current={isAnnouncementSettingsActive ? "page" : undefined}
              onClick={onSelectAnnouncementSettings}
            >
              {t("workspace.settings.announcements")}
            </button>
            <button
              className={
                isGithubSettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isGithubSettingsActive ? "page" : undefined}
              onClick={onSelectGithubSettings}
            >
              {t("workspace.settings.github")}
            </button>
            <button
              className={
                isGlobalMemorySettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isGlobalMemorySettingsActive ? "page" : undefined}
              onClick={onSelectGlobalMemorySettings}
            >
              {t("workspace.settings.globalMemory")}
            </button>
            <button
              className={
                isLanguageSettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isLanguageSettingsActive ? "page" : undefined}
              onClick={onSelectLanguageSettings}
            >
              {t("workspace.settings.language")}
            </button>
            <button
              className={
                isNetworkSettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isNetworkSettingsActive ? "page" : undefined}
              onClick={onSelectNetworkSettings}
            >
              {t("workspace.settings.network")}
            </button>
            <button
              className={
                isAccessManagementSettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isAccessManagementSettingsActive ? "page" : undefined}
              onClick={onSelectAccessManagementSettings}
            >
              {t("workspace.settings.accessManagement")}
            </button>
            <button
              className={isAccessSecuritySettingsActive
                ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                : "workspace-settings-panel__standalone"}
              type="button"
              aria-current={isAccessSecuritySettingsActive ? "page" : undefined}
              onClick={onSelectAccessSecuritySettings}
            >
              {t("workspace.settings.accessSecurity")}
            </button>
            <button
              className={
                isTokenEstimationSettingsActive
                  ? "workspace-settings-panel__standalone workspace-settings-panel__standalone--active"
                  : "workspace-settings-panel__standalone"
              }
              type="button"
              aria-current={isTokenEstimationSettingsActive ? "page" : undefined}
              onClick={onSelectTokenEstimationSettings}
            >
              {t("workspace.settings.tokenEstimation")}
            </button>
            <div className="workspace-settings-panel__item-group">
              <button
                className={[
                  "workspace-settings-panel__group-button",
                  isFunctionalModelGroupOpen
                    ? "workspace-settings-panel__group-button--open"
                    : "",
                  isFunctionalModelGroupActive
                    ? "workspace-settings-panel__group-button--active"
                    : "",
                ].filter(Boolean).join(" ")}
                type="button"
                aria-expanded={isFunctionalModelGroupOpen}
                aria-controls="workspace-functional-model-settings-subitems"
                onClick={onToggleFunctionalModelGroup}
              >
                <span className="workspace-settings-panel__group-label">
                  {t("workspace.settings.functionalModel")}
                </span>
                <span className="workspace-settings-panel__group-chevron" aria-hidden="true">
                  <CaretRight size={14} weight="bold" />
                </span>
              </button>
              <div
                id="workspace-functional-model-settings-subitems"
                className={isFunctionalModelGroupOpen
                  ? "workspace-settings-panel__subitems workspace-settings-panel__subitems--open"
                  : "workspace-settings-panel__subitems"}
                aria-label={t("workspace.settings.functionalModelCategories")}
              >
                <div className="workspace-settings-panel__subitems-inner">
                  {functionalModelSettingsSections.map((section) => (
                    <button
                      key={section.id}
                      className={
                        activeSettingsSectionId === section.id
                          ? "workspace-settings-panel__subitem workspace-settings-panel__subitem--active"
                          : "workspace-settings-panel__subitem"
                      }
                      type="button"
                      aria-current={
                        activeSettingsSectionId === section.id
                          ? "page"
                          : undefined
                      }
                      onClick={() => onSelectFunctionalModelSection(section.id)}
                    >
                      {t(section.labelKey)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </nav>
    </aside>
  );

  const renderPanel = (section: HoverSidebarSectionId) =>
    section === "overview" ? (
      <WorkspaceProjectsPanel
        documentTabs={documentTabs}
        onReferenceProjectFile={onReferenceProjectFile}
        projectCatalog={projectCatalog}
      />
    ) : section === "knowledge" ? (
      <WorkspaceProjectsPanel
        allowExternalImport={false}
        documentTabs={documentTabs}
        onReferenceProjectFile={onReferenceProjectFile}
        projectCatalog={knowledgeProjectCatalog}
      />
    ) : section === "experience" ? (
      <WorkspaceProjectsPanel
        allowExternalImport={false}
        documentTabs={documentTabs}
        onReferenceProjectFile={onReferenceProjectFile}
        projectCatalog={experienceProjectCatalog}
      />
    ) : section === "roles" ? (
      <WorkspaceProjectsPanel
        allowExternalImport={false}
        documentTabs={documentTabs}
        onReferenceProjectFile={onReferenceProjectFile}
        projectCatalog={roleProjectCatalog}
      />
    ) : section === "themes" ? (
      <WorkspaceProjectsPanel
        allowExternalImport={false}
        documentTabs={documentTabs}
        onReferenceProjectFile={onReferenceProjectFile}
        projectCatalog={themeProjectCatalog}
      />
    ) : section === "models" ? (
      providerProjectCatalog.expandedProject ? (
        <WorkspaceProjectsPanel
          allowCreateProject={false}
          allowExternalImport={false}
          documentTabs={documentTabs}
          onReferenceProjectFile={onReferenceProjectFile}
          projectCatalog={providerProjectCatalog}
        />
      ) : (
        <ProviderCatalogPanel
          categoryId={providerProjectCatalog.selectedCategoryId}
          onOpenProvider={onOpenProvider}
          onMoveProviderToCategory={(providerId, categoryId) => {
            const project = providerProjectCatalog.items.find(
              (item) => item.root_path.split(/[\\/]/).at(-1) === providerId,
            );
            if (!project) return;
            void providerProjectCatalog.moveProjectToCategory(
              project.project_id,
              categoryId,
            );
          }}
          providerCatalog={providerCatalog}
          visibleProviderIds={new Set(
            providerProjectCatalog.selectedCategoryProjects.map((project) =>
              project.root_path.split(/[\\/]/).at(-1) ?? ""
            ),
          )}
          targetCategories={providerProjectCatalog.categories.filter(
            (category) => category.category_id !== providerProjectCatalog.selectedCategoryId,
          )}
        />
      )
    ) : section === "tools" ? (
      <ToolCatalogPanel
        browser={toolBrowser}
        documentTabs={toolDocumentTabs}
        toolCatalog={toolCatalog}
        toolFolders={toolFolders}
      />
    ) : section === "settings" ? (
      renderSettingsPanel()
    ) : null;
  const renderedSections = WORKSPACE_SIDE_PANEL_SECTIONS.filter((section) =>
    section === activeSection || visitedSections.has(section)
  );
  const getPanelClassName = (section: HoverSidebarSectionId) => {
    if (section !== activeSection) {
      return "workspace-page__side-panel-view workspace-page__side-panel-view--static workspace-page__side-panel-view--hidden";
    }
    if (!transitionState) {
      return "workspace-page__side-panel-view workspace-page__side-panel-view--static";
    }
    return transitionState.direction === "up"
      ? "workspace-page__side-panel-view workspace-page__side-panel-view--static workspace-page__side-panel-view--enter-from-up"
      : "workspace-page__side-panel-view workspace-page__side-panel-view--static workspace-page__side-panel-view--enter-from-down";
  };

  return (
    <div
      className="workspace-page__side-panel"
      style={{ width: sidePanelWidth }}
    >
      <div className="workspace-page__side-panel-stage">
        {renderedSections.map((section) => (
          <div
            key={section}
            className={getPanelClassName(section)}
            aria-hidden={section === activeSection ? undefined : "true"}
          >
            {renderPanel(section)}
          </div>
        ))}
      </div>
    </div>
  );
});

function normalizeSettingsSearchText(value: string) {
  return value.trim().toLowerCase();
}
