import { ArrowSquareIn } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../../entities/project/model/project";
import type { ConversationRoleCatalogItem } from "../../../entities/role-configuration/model/roleConfiguration";
import { getConversationRoles } from "../../../services/project/getConversationRoles";
import "../../../shared/ui/specialized-collection-overview/specialized-collection-overview.css";

type RoleCollectionOverviewProps = {
  isActive: boolean;
  onOpenProject: (projectId: string) => void;
  onSelectProject: (projectId: string) => void;
  projects: Project[];
  selectedProjectId: string | null;
};

export function RoleCollectionOverview({
  isActive,
  onOpenProject,
  onSelectProject,
  projects,
  selectedProjectId,
}: RoleCollectionOverviewProps) {
  const [roles, setRoles] = useState<ConversationRoleCatalogItem[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const projectKey = projects.map((project) => project.project_id).join("|");

  useEffect(() => {
    if (!isActive) return;
    let disposed = false;
    setState("loading");
    setError(null);
    void getConversationRoles()
      .then((catalog) => {
        if (disposed) return;
        setRoles(catalog.roles);
        setState("ready");
      })
      .catch((loadError: unknown) => {
        if (disposed) return;
        setRoles([]);
        setState("error");
        setError(loadError instanceof Error ? loadError.message : "角色总览加载失败。");
      });
    return () => {
      disposed = true;
    };
  }, [isActive, projectKey]);

  const rolesByProjectId = useMemo(
    () => new Map(roles.map((role) => [role.role_project_id, role])),
    [roles],
  );

  if (state === "loading") {
    return <div className="specialized-collection-overview__state">正在加载角色总览…</div>;
  }
  if (state === "error") {
    return (
      <div className="specialized-collection-overview__state specialized-collection-overview__state--error">
        {error ?? "角色总览加载失败。"}
      </div>
    );
  }
  if (projects.length === 0) {
    return <div className="specialized-collection-overview__state">当前分类没有角色。</div>;
  }

  return (
    <section className="specialized-collection-overview" aria-label="角色总览">
      <div className="specialized-collection-overview__grid">
        {projects.map((project) => {
          const role = rolesByProjectId.get(project.project_id) ?? null;
          const isSelected = selectedProjectId === project.project_id;
          return (
            <article
              className={
                isSelected
                  ? "specialized-collection-overview__card specialized-collection-overview__card--selected"
                  : "specialized-collection-overview__card"
              }
              key={project.project_id}
              onClick={() => onSelectProject(project.project_id)}
              onDoubleClick={() => onOpenProject(project.project_id)}
            >
              <header className="specialized-collection-overview__header">
                <span className="specialized-collection-overview__identity">
                  <strong title={project.name}>{project.name}</strong>
                </span>
              </header>
              <p className="specialized-collection-overview__description">
                {role?.description?.trim() || "尚未填写角色说明。"}
              </p>
              <footer className="specialized-collection-overview__footer">
                <span>{formatUpdatedAt(project.updated_at)}</span>
                <button
                  className="specialized-collection-overview__enter"
                  type="button"
                  aria-label={`进入角色 ${project.name}`}
                  title="进入角色工作区"
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpenProject(project.project_id);
                  }}
                >
                  <ArrowSquareIn size={15} aria-hidden="true" />
                </button>
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function formatUpdatedAt(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}
