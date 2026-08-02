import { lazy, Suspense } from "react";

import type {
  ProjectOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { ProjectOverviewViewTabs } from "../../../features/project-category-overview/ui/ProjectOverviewViewTabs";
import type { ProjectMarketScope } from "../../../features/project-market/model/projectMarket";
import "./project-branch-overview-panel.css";

const ConversationBranchDashboard = lazy(async () => {
  const module = await import(
    "../../../features/conversation-branch-dashboard/ui/ConversationBranchDashboard"
  );
  return { default: module.ConversationBranchDashboard };
});

type ProjectBranchOverviewPanelProps = {
  activeMessageId: string | null;
  activeSessionId: string | null;
  isActive: boolean;
  onOverviewViewChange: (view: ProjectOverviewView) => void;
  onSelectExportDirectory?: () => Promise<string | null>;
  onSelectMessage: (sessionId: string, messageId: string) => void;
  projectId: string | null;
  projectRootPath: string;
  marketScope?: ProjectMarketScope | null;
  showOverviewTabs?: boolean;
};

export function ProjectBranchOverviewPanel({
  activeMessageId,
  activeSessionId,
  isActive,
  onOverviewViewChange,
  onSelectExportDirectory,
  onSelectMessage,
  projectId,
  projectRootPath,
  marketScope = "project",
  showOverviewTabs = true,
}: ProjectBranchOverviewPanelProps) {
  return (
    <section
      className={[
        "project-branch-overview-panel",
        showOverviewTabs
          ? ""
          : "project-branch-overview-panel--without-tabs",
      ].filter(Boolean).join(" ")}
    >
      {showOverviewTabs ? (
        <ProjectOverviewViewTabs
          activeView="branches"
          disabled={!projectId}
          marketScope={marketScope}
          onChange={onOverviewViewChange}
        />
      ) : null}
      <Suspense
        fallback={(
          <div className="project-branch-overview-panel__loading">
            正在加载分支看板...
          </div>
        )}
      >
        <ConversationBranchDashboard
          activeMessageId={activeMessageId}
          activeSessionId={activeSessionId}
          isActive={isActive}
          onSelectExportDirectory={onSelectExportDirectory}
          onSelectMessage={onSelectMessage}
          projectId={projectId}
          projectRootPath={projectRootPath}
        />
      </Suspense>
    </section>
  );
}
