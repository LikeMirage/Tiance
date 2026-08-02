import type { ReactNode } from "react";

import type { ProjectOverviewItem } from "../../../entities/project/model/project";

type ProjectOverviewStackProps = {
  expandedProjectId: string | null;
  getExpandLabel: (item: ProjectOverviewItem) => string;
  items: ProjectOverviewItem[];
  onExpand: (projectId: string) => void;
  renderProjectCard: (item: ProjectOverviewItem) => ReactNode;
};

export function ProjectOverviewStack({
  expandedProjectId,
  getExpandLabel,
  items,
  onExpand,
  renderProjectCard,
}: ProjectOverviewStackProps) {
  return items.map((item) => {
    const projectId = item.project.project_id;
    const isExpanded = projectId === expandedProjectId;
    return (
      <div
        key={projectId}
        className={[
          "project-category-overview__stack-item",
          isExpanded
            ? "project-category-overview__stack-item--expanded"
            : "project-category-overview__stack-item--collapsed",
        ].join(" ")}
      >
        <div
          className="project-category-overview__stack-card"
          aria-hidden={isExpanded ? undefined : "true"}
          inert={isExpanded ? undefined : true}
        >
          {renderProjectCard(item)}
        </div>
        {!isExpanded ? (
          <button
            className="project-category-overview__stack-select"
            type="button"
            aria-label={getExpandLabel(item)}
            onClick={() => onExpand(projectId)}
          />
        ) : null}
      </div>
    );
  });
}
