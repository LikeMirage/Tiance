import { lazy } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";

export type ToolDashboardView = "basics" | "examples" | "dependencies" | "callRecords";

export type ToolFolderTarget = {
  folderId: string;
  toolsetId: string;
} | null;

const ToolCallRecordsDashboard = lazy(() =>
  import("../../tool-call-records-dashboard/ui/ToolCallRecordsDashboard").then((module) => ({
    default: module.ToolCallRecordsDashboard,
  })),
);
const ToolDependenciesDashboard = lazy(() =>
  import("../../tool-dependencies-dashboard/ui/ToolDependenciesDashboard").then((module) => ({
    default: module.ToolDependenciesDashboard,
  })),
);
const ToolManifestDashboard = lazy(() =>
  import("../../tool-manifest-dashboard/ui/ToolManifestDashboard").then((module) => ({
    default: module.ToolManifestDashboard,
  })),
);

export function ToolDashboardContent({
  activeTab,
  onSaveTab,
  onUpdateContent,
  toolCallRecordTarget,
  toolDashboardView,
  toolDependencyTarget,
  toolEntryCandidates,
}: {
  activeTab: DocumentTab;
  onSaveTab: (id: string, contentSnapshot?: string) => Promise<boolean>;
  onUpdateContent: (id: string, content: string) => void;
  toolCallRecordTarget: ToolFolderTarget;
  toolDashboardView: ToolDashboardView;
  toolDependencyTarget: ToolFolderTarget;
  toolEntryCandidates: string[];
}) {
  if (toolDashboardView === "dependencies") {
    return toolDependencyTarget ? (
      <ToolDependenciesDashboard
        folderId={toolDependencyTarget.folderId}
        toolsetId={toolDependencyTarget.toolsetId}
      />
    ) : (
      <div className="doc-editor__empty">无法识别当前工具依赖目标。</div>
    );
  }

  if (toolDashboardView === "callRecords") {
    return toolCallRecordTarget ? (
      <ToolCallRecordsDashboard
        folderId={toolCallRecordTarget.folderId}
        toolsetId={toolCallRecordTarget.toolsetId}
      />
    ) : (
      <div className="doc-editor__empty">无法识别当前工具调用记录目标。</div>
    );
  }

  return (
    <ToolManifestDashboard
      content={activeTab.content}
      entryCandidates={toolEntryCandidates}
      isDirty={activeTab.isDirty}
      saveError={activeTab.saveError}
      saveState={activeTab.saveState}
      view={toolDashboardView}
      onChange={(content) => onUpdateContent(activeTab.id, content)}
      onSave={(content) => onSaveTab(activeTab.id, content)}
    />
  );
}
