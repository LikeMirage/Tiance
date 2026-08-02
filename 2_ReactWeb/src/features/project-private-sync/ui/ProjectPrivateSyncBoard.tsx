import {
  ArrowDown,
  ArrowUp,
  CaretRight,
  CheckSquare,
  File,
  FolderSimple,
  GitBranch,
  MinusSquare,
  Square,
  X,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import type {
  GithubProjectSyncFile,
  GithubProjectSyncProject,
} from "../../../services/github/githubSyncApi";
import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import { useProjectPrivateSync } from "../model/useProjectPrivateSync";
import "./project-private-sync-board.css";

type ProjectPrivateSyncBoardProps = {
  active: boolean;
  header: (refresh: () => Promise<unknown>, loading: boolean) => React.ReactNode;
};

const key = (suffix: string) => `githubProjectSync.${suffix}` as TranslationKey;

export function ProjectPrivateSyncBoard({ active, header }: ProjectPrivateSyncBoardProps) {
  const { t } = useI18n();
  const sync = useProjectPrivateSync(active);
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);

  const activeCategory = sync.board?.categories.find(
    (category) => category.categoryId === activeCategoryId,
  ) ?? sync.board?.categories[0] ?? null;
  const categoryProjects = useMemo(() => (
    sync.board?.projects.filter((project) => (
      activeCategory?.projectIds.includes(project.projectId)
    )) ?? []
  ), [activeCategory?.projectIds, sync.board?.projects]);
  const activeProject = categoryProjects.find(
    (project) => project.projectId === activeProjectId,
  ) ?? categoryProjects[0] ?? null;

  const changedPathsForProject = (project: GithubProjectSyncProject) => project.files
    .filter((file) => file.status !== "same")
    .map((file) => file.path);
  const selectedCount = sync.selectedPaths.size;

  return (
    <section className="project-private-sync-board">
      {header(sync.refresh, sync.loading)}
      <div className="project-private-sync-board__summary">
        <span><GitBranch size={15} />{sync.board?.branch ?? "main"}</span>
        <strong>{t(key("changed"), { count: sync.board?.changedFiles ?? 0 })}</strong>
      </div>

      {sync.error ? (
        <div className="project-private-sync-board__error" role="alert">
          <span>{sync.error}</span>
          <button onClick={() => void sync.refresh()} type="button">{t(key("retry"))}</button>
        </div>
      ) : null}

      {!sync.board && sync.loading ? (
        <div className="project-private-sync-board__state">{t(key("loadingBoard"))}</div>
      ) : sync.board ? (
        <div className="project-private-sync-board__columns">
          <SyncColumn title={t(key("categories"))}>
            {sync.board.categories.map((category) => {
              const paths = sync.board!.projects
                .filter((project) => category.projectIds.includes(project.projectId))
                .flatMap(changedPathsForProject);
              return (
                <SyncRow
                  active={category.categoryId === activeCategory?.categoryId}
                  count={category.changedFiles}
                  key={category.categoryId}
                  label={category.name}
                  onOpen={() => {
                    setActiveCategoryId(category.categoryId);
                    setActiveProjectId(null);
                  }}
                  onToggle={() => sync.togglePaths(paths)}
                  selected={selectionState(paths, sync.selectedPaths)}
                />
              );
            })}
          </SyncColumn>

          <SyncColumn title={t(key("projects"))}>
            {categoryProjects.map((project) => {
              const paths = changedPathsForProject(project);
              return (
                <SyncRow
                  active={project.projectId === activeProject?.projectId}
                  count={project.changedFiles}
                  key={project.projectId}
                  label={project.name}
                  meta={t(key(`location.${project.location}`))}
                  onOpen={() => setActiveProjectId(project.projectId)}
                  onToggle={() => sync.togglePaths(paths)}
                  selected={selectionState(paths, sync.selectedPaths)}
                />
              );
            })}
          </SyncColumn>

          <SyncColumn title={t(key("files"))}>
            {activeProject?.files.map((file) => (
              <FileRow
                file={file}
                key={file.path}
                onToggle={() => sync.togglePaths([file.path])}
                selected={sync.selectedPaths.has(file.path)}
              />
            ))}
          </SyncColumn>
        </div>
      ) : null}

      <footer className="project-private-sync-board__actions">
        <span>{t(key("selected"), { count: selectedCount })}</span>
        <button
          disabled={selectedCount === 0 || sync.loading}
          onClick={() => void sync.preview("pull")}
          type="button"
        >
          <ArrowDown size={15} />{t(key("pull"))}
        </button>
        <button
          disabled={selectedCount === 0 || sync.loading}
          onClick={() => void sync.preview("push")}
          type="button"
        >
          <ArrowUp size={15} />{t(key("push"))}
        </button>
      </footer>

      {sync.plan ? (
        <SyncPlanDialog
          apply={sync.apply}
          close={sync.clearPlan}
          loading={sync.loading}
          plan={sync.plan}
        />
      ) : null}
    </section>
  );
}

function SyncColumn({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <section className="project-private-sync-board__column">
      <header>{title}</header>
      <div>{children}</div>
    </section>
  );
}

function SyncRow({
  active,
  count,
  label,
  meta,
  onOpen,
  onToggle,
  selected,
}: {
  active: boolean;
  count: number;
  label: string;
  meta?: string;
  onOpen: () => void;
  onToggle: () => void;
  selected: "none" | "some" | "all";
}) {
  const Icon = selected === "all" ? CheckSquare : selected === "some" ? MinusSquare : Square;
  return (
    <div className={`project-private-sync-row${active ? " is-active" : ""}`}>
      <button aria-label={label} disabled={count === 0} onClick={onToggle} type="button">
        <Icon size={16} weight={selected === "none" ? "regular" : "fill"} />
      </button>
      <button onClick={onOpen} type="button">
        <FolderSimple size={16} />
        <span><strong>{label}</strong>{meta ? <small>{meta}</small> : null}</span>
        <b>{count}</b><CaretRight size={13} />
      </button>
    </div>
  );
}

function FileRow({
  file,
  onToggle,
  selected,
}: {
  file: GithubProjectSyncFile;
  onToggle: () => void;
  selected: boolean;
}) {
  const { t } = useI18n();
  return (
    <button
      className={`project-private-sync-file${selected ? " is-selected" : ""}`}
      disabled={file.status === "same"}
      onClick={onToggle}
      type="button"
    >
      {selected ? <CheckSquare size={16} weight="fill" /> : <Square size={16} />}
      <File size={15} />
      <span title={file.relativePath}>{file.relativePath}</span>
      <small data-status={file.status}>{t(key(`status.${file.status}`))}</small>
    </button>
  );
}

function SyncPlanDialog({ apply, close, loading, plan }: {
  apply: (message: string | null) => Promise<boolean>;
  close: () => void;
  loading: boolean;
  plan: import("../../../services/github/githubSyncApi").GithubSyncPlan;
}) {
  const { t } = useI18n();
  const [message, setMessage] = useState("");
  return (
    <div className="project-private-sync-plan__backdrop">
      <section className="project-private-sync-plan" role="dialog" aria-modal="true">
        <header>
          <div>
            <strong>{t(key(plan.direction === "push" ? "confirmPushTitle" : "confirmPullTitle"))}</strong>
            <small>{t(key("planSummary"), {
              add: plan.additions,
              delete: plan.deletions,
              update: plan.updates,
            })}</small>
          </div>
          <button disabled={loading} onClick={close} type="button"><X size={17} /></button>
        </header>
        <div className="project-private-sync-plan__files">
          {plan.changes.map((change) => (
            <div key={change.path}>
              <b data-kind={change.kind}>{change.kind === "add" ? "+" : change.kind === "delete" ? "−" : "~"}</b>
              <span>{change.path}</span>
            </div>
          ))}
        </div>
        {plan.direction === "push" ? (
          <input
            onChange={(event) => setMessage(event.target.value)}
            placeholder={t(key("commitPlaceholder"))}
            value={message}
          />
        ) : null}
        <footer>
          <button disabled={loading} onClick={close} type="button">{t(key("cancel"))}</button>
          <button
            className="is-primary"
            disabled={loading}
            onClick={() => void apply(plan.direction === "push" ? message || null : null)}
            type="button"
          >
            {loading ? t(key("applying")) : t(key(plan.direction === "push" ? "confirmPush" : "confirmPull"))}
          </button>
        </footer>
      </section>
    </div>
  );
}

function selectionState(paths: readonly string[], selected: ReadonlySet<string>) {
  if (paths.length === 0 || paths.every((path) => !selected.has(path))) return "none" as const;
  return paths.every((path) => selected.has(path)) ? "all" as const : "some" as const;
}
