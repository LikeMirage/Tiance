import { lazy, Suspense } from "react";

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
  onSelectExportDirectory?: () => Promise<string | null>;
  onSelectMessage: (sessionId: string, messageId: string) => void;
  projectId: string | null;
  projectRootPath: string;
};

export function ProjectBranchOverviewPanel({
  activeMessageId,
  activeSessionId,
  isActive,
  onSelectExportDirectory,
  onSelectMessage,
  projectId,
  projectRootPath,
}: ProjectBranchOverviewPanelProps) {
  return (
    <section className="project-branch-overview-panel">
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
