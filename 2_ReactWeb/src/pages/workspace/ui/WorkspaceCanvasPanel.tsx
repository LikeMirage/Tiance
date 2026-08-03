import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type {
  ProviderCatalogEntry,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import type {
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import type { ProjectFileReferenceRequest } from "../../../entities/project/model/projectFileDragData";
import type { ToolFolder } from "../../../entities/tool/model/toolset";
import type { Toolset } from "../../../entities/tool/model/toolset";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import {
  functionalModelSettingsSections,
  type FunctionalModelSettingsSectionId,
} from "../../../features/functional-model-settings/model/functionalModelSections";
import type { ProjectEntryWarmupOptions } from "../../../features/project-entry/model/projectEntryWarmup";
import { FunctionalModelSettingsPanel } from "../../../features/functional-model-settings/ui/FunctionalModelSettingsPanel";
import { TokenEstimationSettingsPanel } from "../../../features/token-estimation-settings/ui/TokenEstimationSettingsPanel";
import { NetworkSettingsPanel } from "../../../features/network-settings/ui/NetworkSettingsPanel";
import { LanguageSettingsPanel } from "../../../features/locale-settings/ui/LanguageSettingsPanel";
import { GithubSettingsPanel } from "../../../features/github-settings/ui/GithubSettingsPanel";
import { SoftwareUpdatePanel } from "../../../features/software-update/ui/SoftwareUpdatePanel";
import type { UseProviderModelDiscoveryResult } from "../../../features/provider-model-discovery/model/useProviderModelDiscovery";
import type { HoverSidebarSectionId } from "../../../widgets/hover-sidebar/model/sidebarSections";
import type { UseProviderConfigStateResult } from "../../../features/provider-config/model/useProviderConfigState";
import type { WorkspaceSettingsSectionId } from "../model/workspaceSettingsSections";
import { WorkspaceEditorCanvasPanel } from "./WorkspaceEditorCanvasPanel";
import { WorkspaceProviderCanvasPanel } from "./WorkspaceProviderCanvasPanel";
import { WorkspaceToolCanvasPanel } from "./WorkspaceToolCanvasPanel";
import "./workspace-canvas-panel.css";

type WorkspaceCanvasPanelProps = {
  activeSection: HoverSidebarSectionId;
  activeFunctionalModelSectionId: FunctionalModelSettingsSectionId;
  activeSettingsSectionId: WorkspaceSettingsSectionId;
  activeThemeId: string | null;
  isThemeLoading: boolean;
  activeToolWorkspaceKey: string | null;
  projectWorkspaceError?: string | null;
  projectFileReferenceRequest?: ProjectFileReferenceRequest | null;
  projectDocumentTabs: ReturnType<typeof useDocumentTabs>;
  layoutPreferences: WorkspaceLayoutPreferences;
  isRenamingProvider: boolean;
  isUpdatingProviderProtocol: boolean;
  onSelectFunctionalModelSection: (sectionId: FunctionalModelSettingsSectionId) => void;
  onExpandProject: (
    projectId: string,
    options?: ProjectEntryWarmupOptions,
  ) => boolean | void | Promise<boolean | void>;
  onCreateProject: () => Promise<void>;
  onCreateKnowledgeProject: () => Promise<void>;
  onCreateExperienceProject: () => Promise<void>;
  onCreateRoleProject: () => Promise<void>;
  onCollapseProject: () => boolean | void | Promise<boolean | void>;
  onConfirmProjectSession: (projectId: string, sessionId: string | null) => void;
  onImportProjectFolder: (rootPath: string) => Promise<void>;
  onApplyTheme: (themeId: string) => void;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onPrepareProject?: (projectId: string) => void;
  onSelectProjectCategory: (categoryId: string) => void;
  onSelectProject: (
    projectId: string,
    options?: ProjectEntryWarmupOptions,
  ) => boolean | void | Promise<boolean | void>;
  onOpenToolFolder: (folderId: string) => void;
  onCollapseToolFolder: () => Promise<boolean>;
  onSelectToolFolder: (folderId: string) => void;
  onReloadToolFolders: () => void;
  onRevealToolFolder: (folderId: string) => Promise<void>;
  onSelectToolset: (toolsetId: string) => void;
  onToolManifestSaved?: () => void;
  onRenameProvider: (providerId: string, displayName: string) => Promise<void>;
  onUpdateProviderProtocol: (
    providerId: string,
    protocolFamily: ProviderProtocolFamily,
  ) => Promise<void>;
  providerConfigState: UseProviderConfigStateResult;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  providerProjectCategories: ProjectCategory[];
  providerProjects: Project[];
  providerSelectedCategoryId: string | null;
  providerExpandedProjectId: string | null;
  providerSelectedProject: Project | null;
  providerSelectedSessionId: string | null;
  projectCategories: ProjectCategory[];
  projects: Project[];
  knowledgeProjectCategories: ProjectCategory[];
  knowledgeProjects: Project[];
  knowledgeSelectedCategoryId: string | null;
  knowledgeExpandedProjectId: string | null;
  knowledgeSelectedProject: Project | null;
  knowledgeSelectedSessionId: string | null;
  experienceProjectCategories: ProjectCategory[];
  experienceProjects: Project[];
  experienceSelectedCategoryId: string | null;
  experienceExpandedProjectId: string | null;
  experienceSelectedProject: Project | null;
  experienceSelectedSessionId: string | null;
  roleProjectCategories: ProjectCategory[];
  roleProjects: Project[];
  roleSelectedCategoryId: string | null;
  roleExpandedProjectId: string | null;
  roleSelectedProject: Project | null;
  roleSelectedSessionId: string | null;
  themeProjectCategories: ProjectCategory[];
  themeProjects: Project[];
  themeSelectedCategoryId: string | null;
  themeExpandedProjectId: string | null;
  themeSelectedProject: Project | null;
  themeSelectedSessionId: string | null;
  selectedCategoryId: string | null;
  expandedProjectId: string | null;
  selectedProject: Project | null;
  selectedSessionId: string | null;
  selectedProvider: ProviderCatalogEntry | null;
  selectedToolFolder: ToolFolder | null;
  expandedToolFolder: ToolFolder | null;
  selectedToolset: Toolset | null;
  toolFolders: ToolFolder[];
  toolFoldersError?: string | null;
  toolFoldersReadonly: boolean;
  toolFoldersState: "idle" | "loading" | "ready" | "error";
  toolDocumentTabs: ReturnType<typeof useDocumentTabs>;
  toolEntryFilePaths: string[];
  toolsets: Toolset[];
  toolWorkspaceError?: string | null;
};

const WORKSPACE_CANVAS_SECTIONS: readonly HoverSidebarSectionId[] = [
  "overview",
  "knowledge",
  "experience",
  "roles",
  "themes",
  "models",
  "tools",
  "settings",
];
const WORKSPACE_CANVAS_TRANSITION_MS = 320;

type CanvasTransitionState = {
  from: HoverSidebarSectionId;
  to: HoverSidebarSectionId;
};

export const WorkspaceCanvasPanel = memo(function WorkspaceCanvasPanel({
  activeSection,
  activeFunctionalModelSectionId,
  activeSettingsSectionId,
  activeThemeId,
  isThemeLoading,
  activeToolWorkspaceKey,
  projectWorkspaceError = null,
  projectFileReferenceRequest = null,
  projectDocumentTabs,
  layoutPreferences,
  isRenamingProvider,
  isUpdatingProviderProtocol,
  onExpandProject,
  onCreateProject,
  onCreateKnowledgeProject,
  onCreateExperienceProject,
  onCreateRoleProject,
  onCollapseProject,
  onConfirmProjectSession,
  onImportProjectFolder,
  onApplyTheme,
  onLayoutPreferenceChange,
  onPrepareProject,
  onSelectProjectCategory,
  onSelectProject,
  onSelectFunctionalModelSection,
  onOpenToolFolder,
  onCollapseToolFolder,
  onSelectToolFolder,
  onReloadToolFolders,
  onRevealToolFolder,
  onSelectToolset,
  onToolManifestSaved,
  onRenameProvider,
  onUpdateProviderProtocol,
  providerConfigState,
  providerModelDiscovery,
  providerProjectCategories,
  providerProjects,
  providerSelectedCategoryId,
  providerExpandedProjectId,
  providerSelectedProject,
  providerSelectedSessionId,
  projectCategories,
  projects,
  knowledgeProjectCategories,
  knowledgeProjects,
  knowledgeSelectedCategoryId,
  knowledgeExpandedProjectId,
  knowledgeSelectedProject,
  knowledgeSelectedSessionId,
  experienceProjectCategories,
  experienceProjects,
  experienceSelectedCategoryId,
  experienceExpandedProjectId,
  experienceSelectedProject,
  experienceSelectedSessionId,
  roleProjectCategories,
  roleProjects,
  roleSelectedCategoryId,
  roleExpandedProjectId,
  roleSelectedProject,
  roleSelectedSessionId,
  themeProjectCategories,
  themeProjects,
  themeSelectedCategoryId,
  themeExpandedProjectId,
  themeSelectedProject,
  themeSelectedSessionId,
  selectedCategoryId,
  expandedProjectId,
  selectedProject,
  selectedSessionId,
  selectedProvider,
  selectedToolFolder,
  expandedToolFolder,
  selectedToolset,
  toolFolders,
  toolFoldersError = null,
  toolFoldersReadonly,
  toolFoldersState,
  toolDocumentTabs,
  toolEntryFilePaths,
  toolsets,
  toolWorkspaceError = null,
}: WorkspaceCanvasPanelProps) {
  const previousSectionRef = useRef(activeSection);
  const transitionTimerRef = useRef<number | null>(null);
  const [transitionState, setTransitionState] = useState<CanvasTransitionState | null>(null);
  const [readySettingsSections, setReadySettingsSections] = useState<ReadonlySet<WorkspaceSettingsSectionId>>(
    () => new Set<WorkspaceSettingsSectionId>(),
  );
  const [displayedSettingsSectionId, setDisplayedSettingsSectionId] =
    useState<WorkspaceSettingsSectionId>(activeSettingsSectionId);
  const [visitedSections, setVisitedSections] = useState<ReadonlySet<HoverSidebarSectionId>>(
    () => new Set<HoverSidebarSectionId>(["overview"]),
  );

  const markSettingsSectionReady = useCallback((sectionId: WorkspaceSettingsSectionId) => {
    setReadySettingsSections((current) => {
      if (current.has(sectionId)) return current;
      return new Set([...current, sectionId]);
    });
  }, []);

  const markFunctionalModelSettingsReady = useCallback(() => {
    setReadySettingsSections((current) => {
      const next = new Set(current);
      let changed = false;
      for (const section of functionalModelSettingsSections) {
        if (!next.has(section.id)) {
          next.add(section.id);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, []);

  const markTokenEstimationSettingsReady = useCallback(() => {
    markSettingsSectionReady("token-estimation");
  }, [markSettingsSectionReady]);
  const markNetworkSettingsReady = useCallback(() => {
    markSettingsSectionReady("network");
  }, [markSettingsSectionReady]);
  const markLanguageSettingsReady = useCallback(() => {
    markSettingsSectionReady("language");
  }, [markSettingsSectionReady]);
  const markGithubSettingsReady = useCallback(() => {
    markSettingsSectionReady("github");
  }, [markSettingsSectionReady]);
  const markSoftwareUpdateSettingsReady = useCallback(() => {
    markSettingsSectionReady("software-update");
  }, [markSettingsSectionReady]);

  useLayoutEffect(() => {
    const previousSection = previousSectionRef.current;
    if (previousSection === activeSection) {
      return;
    }

    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
    }

    setTransitionState({ from: previousSection, to: activeSection });
    previousSectionRef.current = activeSection;

    transitionTimerRef.current = window.setTimeout(() => {
      setTransitionState(null);
      transitionTimerRef.current = null;
    }, WORKSPACE_CANVAS_TRANSITION_MS);

    return () => {
      if (transitionTimerRef.current !== null) {
        window.clearTimeout(transitionTimerRef.current);
        transitionTimerRef.current = null;
      }
    };
  }, [activeSection]);

  useEffect(() => {
    setVisitedSections((current) => {
      if (current.has(activeSection)) {
        return current;
      }
      return new Set([...current, activeSection]);
    });
  }, [activeSection]);

  useEffect(() => {
    if (readySettingsSections.has(activeSettingsSectionId)) {
      setDisplayedSettingsSectionId(activeSettingsSectionId);
    }
  }, [activeSettingsSectionId, readySettingsSections]);

  const renderCanvasContent = (section: HoverSidebarSectionId) => {
    const isSectionActive = section === activeSection;
    switch (section) {
      case "overview":
        return (
          <WorkspaceEditorCanvasPanel
            categories={projectCategories}
            projectMarketScope="project"
            expandedProjectId={expandedProjectId}
            documentTabs={projectDocumentTabs}
            isActive={isSectionActive}
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCreateProject={onCreateProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onImportProjectFolder={onImportProjectFolder}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={projects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={selectedCategoryId}
            selectedProject={selectedProject}
            selectedSessionId={selectedSessionId}
          />
        );
      case "knowledge":
        return (
          <WorkspaceEditorCanvasPanel
            categories={knowledgeProjectCategories}
            projectMarketScope="knowledge"
            expandedProjectId={knowledgeExpandedProjectId}
            documentTabs={projectDocumentTabs}
            isActive={isSectionActive}
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCreateProject={onCreateKnowledgeProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={knowledgeProjects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={knowledgeSelectedCategoryId}
            selectedProject={knowledgeSelectedProject}
            selectedSessionId={knowledgeSelectedSessionId}
          />
        );
      case "experience":
        return (
          <WorkspaceEditorCanvasPanel
            categories={experienceProjectCategories}
            projectMarketScope="experience"
            expandedProjectId={experienceExpandedProjectId}
            documentTabs={projectDocumentTabs}
            isActive={isSectionActive}
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCreateProject={onCreateExperienceProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={experienceProjects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={experienceSelectedCategoryId}
            selectedProject={experienceSelectedProject}
            selectedSessionId={experienceSelectedSessionId}
          />
        );
      case "roles":
        return (
          <WorkspaceEditorCanvasPanel
            categories={roleProjectCategories}
            expandedProjectId={roleExpandedProjectId}
            documentTabs={projectDocumentTabs}
            isActive={isSectionActive}
            isRoleWorkspace
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCreateProject={onCreateRoleProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={roleProjects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={roleSelectedCategoryId}
            selectedProject={roleSelectedProject}
            selectedSessionId={roleSelectedSessionId}
          />
        );
      case "themes":
        return (
          <WorkspaceEditorCanvasPanel
            categories={themeProjectCategories}
            expandedProjectId={themeExpandedProjectId}
            documentTabs={projectDocumentTabs}
            activeThemeId={activeThemeId}
            isActive={isSectionActive}
            isThemeLoading={isThemeLoading}
            isThemeWorkspace
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onApplyTheme={onApplyTheme}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={themeProjects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={themeSelectedCategoryId}
            selectedProject={themeSelectedProject}
            selectedSessionId={themeSelectedSessionId}
          />
        );
      case "models":
        return (
          <WorkspaceEditorCanvasPanel
            categories={providerProjectCategories}
            expandedProjectId={providerExpandedProjectId}
            documentTabs={projectDocumentTabs}
            isActive={isSectionActive}
            isProviderWorkspace
            layoutPreferences={layoutPreferences}
            onExpandProject={onExpandProject}
            onCollapseProject={onCollapseProject}
            onConfirmProjectSession={onConfirmProjectSession}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onPrepareProject={onPrepareProject}
            onSelectCategory={onSelectProjectCategory}
            onSelectProject={onSelectProject}
            projects={providerProjects}
            projectFileReferenceRequest={projectFileReferenceRequest}
            workspaceError={projectWorkspaceError}
            selectedCategoryId={providerSelectedCategoryId}
            selectedProject={providerSelectedProject}
            selectedSessionId={providerSelectedSessionId}
            providerConfigurationContent={
              selectedProvider && providerConfigState.selectedDraft ? (
                <WorkspaceProviderCanvasPanel
                  isActive={isSectionActive && !providerExpandedProjectId}
                  isRenamingProvider={isRenamingProvider}
                  isUpdatingProviderProtocol={isUpdatingProviderProtocol}
                  onRenameProvider={onRenameProvider}
                  onUpdateProviderProtocol={onUpdateProviderProtocol}
                  providerConfigState={providerConfigState}
                  providerModelDiscovery={providerModelDiscovery}
                  selectedProvider={selectedProvider}
                />
              ) : null
            }
          />
        );
      case "settings":
        return (
          <WorkspaceSettingsCanvas
            activeFunctionalModelSectionId={activeFunctionalModelSectionId}
            displayedSettingsSectionId={displayedSettingsSectionId}
            onFunctionalModelSettingsReady={markFunctionalModelSettingsReady}
            onGithubSettingsReady={markGithubSettingsReady}
            onSoftwareUpdateSettingsReady={markSoftwareUpdateSettingsReady}
            onLanguageSettingsReady={markLanguageSettingsReady}
            onNetworkSettingsReady={markNetworkSettingsReady}
            onSelectFunctionalModelSection={onSelectFunctionalModelSection}
            onTokenEstimationSettingsReady={markTokenEstimationSettingsReady}
          />
        );
      case "tools":
        return (
          <WorkspaceToolCanvasPanel
            activeWorkspaceKey={activeToolWorkspaceKey}
            folders={toolFolders}
            documentTabs={toolDocumentTabs}
            folderError={toolFoldersError}
            folderState={toolFoldersState}
            expandedToolFolder={expandedToolFolder}
            isActive={isSectionActive}
            layoutPreferences={layoutPreferences}
            onOpenFolder={onOpenToolFolder}
            onCollapseFolder={onCollapseToolFolder}
            onSelectFolder={onSelectToolFolder}
            onLayoutPreferenceChange={onLayoutPreferenceChange}
            onReloadFolders={onReloadToolFolders}
            onRevealFolder={onRevealToolFolder}
            onSelectToolset={onSelectToolset}
            onToolManifestSaved={onToolManifestSaved}
            readonly={toolFoldersReadonly}
            selectedToolFolder={selectedToolFolder}
            selectedToolset={selectedToolset}
            toolEntryFilePaths={toolEntryFilePaths}
            toolsets={toolsets}
            workspaceError={toolWorkspaceError}
          />
        );
    }
  };

  const renderedSections = WORKSPACE_CANVAS_SECTIONS.filter((section) =>
    section === activeSection ||
    visitedSections.has(section) ||
    transitionState?.from === section
  );
  const getCanvasClassName = (section: HoverSidebarSectionId) => {
    const isActive = section === activeSection;
    const isOutgoing =
      transitionState?.from === section &&
      transitionState.to === activeSection &&
      !isActive;
    return [
      "workspace-page__canvas-view",
      isOutgoing ? "workspace-page__canvas-view--layer" : "workspace-page__canvas-view--static",
      isActive && transitionState?.to === section ? "workspace-page__canvas-view--fade-in" : "",
      isOutgoing ? "workspace-page__canvas-view--fade-out" : "",
      !isActive && !isOutgoing ? "workspace-page__canvas-view--hidden" : "",
    ].filter(Boolean).join(" ");
  };

  return (
    <section className="workspace-page__canvas" aria-label="workspace canvas">
      <div className="workspace-page__canvas-shell">
        <div className="workspace-page__canvas-stage">
          {renderedSections.map((section) => (
            <div
              key={section}
              className={getCanvasClassName(section)}
              aria-hidden={section === activeSection ? undefined : "true"}
            >
              {renderCanvasContent(section)}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

function WorkspaceSettingsCanvas({
  activeFunctionalModelSectionId,
  displayedSettingsSectionId,
  onFunctionalModelSettingsReady,
  onGithubSettingsReady,
  onSoftwareUpdateSettingsReady,
  onLanguageSettingsReady,
  onNetworkSettingsReady,
  onSelectFunctionalModelSection,
  onTokenEstimationSettingsReady,
}: {
  activeFunctionalModelSectionId: FunctionalModelSettingsSectionId;
  displayedSettingsSectionId: WorkspaceSettingsSectionId;
  onFunctionalModelSettingsReady: () => void;
  onGithubSettingsReady: () => void;
  onSoftwareUpdateSettingsReady: () => void;
  onLanguageSettingsReady: () => void;
  onNetworkSettingsReady: () => void;
  onSelectFunctionalModelSection: (sectionId: FunctionalModelSettingsSectionId) => void;
  onTokenEstimationSettingsReady: () => void;
}) {
  const isTokenEstimationDisplayed =
    displayedSettingsSectionId === "token-estimation";
  const isLanguageDisplayed = displayedSettingsSectionId === "language";
  const isGithubDisplayed = displayedSettingsSectionId === "github";
  const isSoftwareUpdateDisplayed = displayedSettingsSectionId === "software-update";
  const isNetworkDisplayed = displayedSettingsSectionId === "network";
  const isFunctionalModelDisplayed =
    !isGithubDisplayed && !isSoftwareUpdateDisplayed && !isLanguageDisplayed && !isTokenEstimationDisplayed && !isNetworkDisplayed;

  return (
    <div className="workspace-page__settings-canvas">
      <div
        className={isSoftwareUpdateDisplayed
          ? "workspace-page__settings-view"
          : "workspace-page__settings-view workspace-page__settings-view--hidden"}
        aria-hidden={isSoftwareUpdateDisplayed ? undefined : "true"}
      >
        <SoftwareUpdatePanel onReady={onSoftwareUpdateSettingsReady} />
      </div>
      <div
        className={
          isGithubDisplayed
            ? "workspace-page__settings-view"
            : "workspace-page__settings-view workspace-page__settings-view--hidden"
        }
        aria-hidden={isGithubDisplayed ? undefined : "true"}
      >
        <GithubSettingsPanel onReady={onGithubSettingsReady} />
      </div>
      <div
        className={
          isLanguageDisplayed
            ? "workspace-page__settings-view"
            : "workspace-page__settings-view workspace-page__settings-view--hidden"
        }
        aria-hidden={isLanguageDisplayed ? undefined : "true"}
      >
        <LanguageSettingsPanel onReady={onLanguageSettingsReady} />
      </div>
      <div
        className={
          isNetworkDisplayed
            ? "workspace-page__settings-view"
            : "workspace-page__settings-view workspace-page__settings-view--hidden"
        }
        aria-hidden={isNetworkDisplayed ? undefined : "true"}
      >
        <NetworkSettingsPanel onReady={onNetworkSettingsReady} />
      </div>
      <div
        className={
          isTokenEstimationDisplayed
            ? "workspace-page__settings-view"
            : "workspace-page__settings-view workspace-page__settings-view--hidden"
        }
        aria-hidden={isTokenEstimationDisplayed ? undefined : "true"}
      >
        <TokenEstimationSettingsPanel
          onReady={onTokenEstimationSettingsReady}
        />
      </div>
      <div
        className={
          isFunctionalModelDisplayed
            ? "workspace-page__settings-view"
            : "workspace-page__settings-view workspace-page__settings-view--hidden"
        }
        aria-hidden={isFunctionalModelDisplayed ? undefined : "true"}
      >
        <FunctionalModelSettingsPanel
          activeSectionId={activeFunctionalModelSectionId}
          onReady={onFunctionalModelSettingsReady}
          onSelectSection={onSelectFunctionalModelSection}
        />
      </div>
    </div>
  );
}
