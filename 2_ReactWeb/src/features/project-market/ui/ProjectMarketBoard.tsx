import {
  FolderSimple,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import { OnlineMarketSourceSelector } from "../../online-market-source/ui/OnlineMarketSourceSelector";
import {
  PROJECT_MARKET_BOARD_CLASSES,
} from "../../../shared/online-market/OnlineMarketBoardControls";
import { OnlineMarketBoardShell } from "../../../shared/online-market/OnlineMarketBoardShell";
import {
  getDefaultProjectMarketSource,
  getProjectMarketPreviewUrl,
} from "../../../services/project-market/projectMarketApi";
import type {
  ProjectMarketInstallOperation,
  ProjectMarketNamespace,
  ProjectMarketProject,
  ProjectMarketScope,
} from "../model/projectMarket";
import {
  filterProjectMarketCategories,
  filterProjectMarketProjects,
  isProjectMarketInstallActive,
  listProjectMarketAuthors,
  listProjectMarketTags,
} from "../model/projectMarketOperations";
import { useProjectMarket } from "../model/useProjectMarket";
import { ProjectMarketFilterPanel } from "./ProjectMarketFilterPanel";
import { ProjectMarketInstallModal } from "./ProjectMarketInstallModal";
import "./project-market-board.css";

export function ProjectMarketBoard({
  categories,
  isActive,
  marketScope = "project",
  selectedCategoryId,
}: {
  categories: readonly ProjectCategory[];
  isActive: boolean;
  marketScope?: ProjectMarketScope;
  selectedCategoryId: string | null;
}) {
  const { language, t } = useI18n();
  const market = useProjectMarket(isActive, marketScope);
  const namespace: ProjectMarketNamespace = marketScope === "knowledge"
    ? "knowledgeMarket"
    : marketScope === "experience"
      ? "experienceMarket"
      : "projectMarket";
  const key = (suffix: string) => `${namespace}.${suffix}` as TranslationKey;
  const sourceInputId = `${marketScope}-market-source`;
  const [query, setQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [pendingProject, setPendingProject] = useState<ProjectMarketProject | null>(null);
  const projects = useMemo(
    () => filterProjectMarketProjects(market.index?.projects ?? [], market.filters, query),
    [market.filters, market.index?.projects, query],
  );
  const authors = useMemo(
    () => listProjectMarketAuthors(market.index?.projects ?? []),
    [market.index?.projects],
  );
  const tags = useMemo(
    () => listProjectMarketTags(market.index?.projects ?? []),
    [market.index?.projects],
  );
  const localCategories = useMemo(
    () => filterProjectMarketCategories(categories, marketScope),
    [categories, marketScope],
  );
  const activeFilterCount = Object.values(market.filters)
    .reduce((total, values) => total + values.length, 0);
  const hasFilters = Boolean(query.trim()) || activeFilterCount > 0;

  return (
    <section className="project-market-board" aria-label={t(key("ariaLabel"))}>
      <OnlineMarketBoardShell
        auxiliary={filterOpen ? (
          <ProjectMarketFilterPanel
            authors={authors}
            filters={market.filters}
            namespace={namespace}
            onChange={market.setFilters}
            tags={tags}
          />
        ) : null}
        auxiliaryClassName="project-market-board__auxiliary"
        classes={PROJECT_MARKET_BOARD_CLASSES}
        content={{
          emptyText: t(key(hasFilters ? "noResults" : "empty")),
          hasError: Boolean(market.error),
          hasIndex: Boolean(market.index),
          hasItems: projects.length > 0,
          isLoading: market.isLoading,
          loadingText: t(key("loading")),
          notConnectedText: t(key("notConnected")),
        }}
        error={{
          error: market.error,
          isLoading: market.isLoading,
          onRetry: () => void market.refresh(),
          retryText: t("common.actions.retry"),
        }}
        source={{
          connectText: t(key("connect")),
          connectingText: t(key("connecting")),
          draftSource: market.draftSource,
          inputId: sourceInputId,
          isLoading: market.isLoading,
          onConnect: () => void market.connect(),
          onDraftSourceChange: market.setDraftSource,
          placeholder: t(key("sourcePlaceholder")),
          refreshText: t("common.actions.refresh"),
          selector: (
            <OnlineMarketSourceSelector
              defaultSource={getDefaultProjectMarketSource(marketScope)}
              disabled={market.isLoading}
              onSelectDefault={() => void market.reset()}
              onSelectSource={(source) => void market.connectTo(source)}
              source={market.draftSource}
            />
          ),
          source: market.source,
        }}
        toolbar={{
          activeFilterCount,
          filterOpen,
          filterText: t(key("filter")),
          isLoading: market.isLoading,
          onFilterToggle: () => setFilterOpen((current) => !current),
          onQueryChange: setQuery,
          onRefresh: () => void market.refresh(),
          query,
          refreshText: t("common.actions.refresh"),
          searchPlaceholder: t(key("searchPlaceholder")),
          status: market.index ? (
            <>
              <strong>{market.index.name}</strong>
              <span>{t(key("projectCount"), { count: market.index.projects.length })}</span>
              <span>{t(key("updatedAt"), {
                value: formatDate(market.index.updatedAt, language),
              })}</span>
              {market.index.cached ? <span>{t(key("cached"))}</span> : null}
            </>
          ) : (
            <span>{market.isLoading ? t(key("loading")) : t(key("notConnected"))}</span>
          ),
        }}
      >
        {projects.map((project) => (
          <ProjectMarketCard
            key={`${market.source}:${project.id}:${project.version}`}
            language={language}
            namespace={namespace}
            onInstall={() => setPendingProject(project)}
            operation={market.installOperations[project.id]}
            project={project}
            source={market.source}
          />
        ))}
      </OnlineMarketBoardShell>

      {pendingProject ? (
        <ProjectMarketInstallModal
          categories={localCategories}
          namespace={namespace}
          onCancel={() => setPendingProject(null)}
          onConfirm={(categoryId) => {
            const projectId = pendingProject.id;
            setPendingProject(null);
            void market.install(projectId, categoryId);
          }}
          project={pendingProject}
          selectedCategoryId={selectedCategoryId}
        />
      ) : null}
    </section>
  );
}

function ProjectMarketCard({
  language,
  namespace,
  onInstall,
  operation,
  project,
  source,
}: {
  language: string;
  namespace: ProjectMarketNamespace;
  onInstall: () => void;
  operation?: ProjectMarketInstallOperation;
  project: ProjectMarketProject;
  source: string;
}) {
  const { t } = useI18n();
  const key = (suffix: string) => `${namespace}.${suffix}` as TranslationKey;
  const [previewFailed, setPreviewFailed] = useState(false);
  const active = isProjectMarketInstallActive(operation?.phase);
  const installed = operation?.phase === "completed" || project.installationStatus === "installed";
  const error = operation?.phase === "failed" ? operation.error : null;

  return (
    <article className="project-market-card">
      <div className="project-market-card__preview">
        {!project.previewPath || previewFailed ? (
          <FolderSimple size={32} weight="thin" aria-hidden="true" />
        ) : (
          <img
            alt={t(key("previewAlt"), { name: project.name })}
            loading="lazy"
            onError={() => setPreviewFailed(true)}
            src={getProjectMarketPreviewUrl(project.previewPath, `${source}:${project.version}`)}
          />
        )}
      </div>
      <div className="project-market-card__body">
        <header>
          <strong title={project.name}>{project.name}</strong>
          <span>v{project.version}</span>
        </header>
        <p>{project.summary}</p>
        {project.tags.length ? (
          <div className="project-market-card__tags">
            {project.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
          </div>
        ) : null}
        <div className="project-market-card__stats">
          {project.stats?.fileCount != null
            ? <span>{t(key("stats.files"), { count: project.stats.fileCount })}</span>
            : null}
          {project.stats?.conversationCount != null
            ? <span>{t(key("stats.conversations"), { count: project.stats.conversationCount })}</span>
            : null}
          {project.stats?.branchCount != null
            ? <span>{t(key("stats.branches"), { count: project.stats.branchCount })}</span>
            : null}
        </div>
        <footer className={error ? "is-error" : undefined}>
          <div>
            <span>{project.author} · {formatDate(project.updatedAt, language)}</span>
            {error ? <small title={error}>{error}</small> : null}
          </div>
          <button disabled={installed || active} onClick={onInstall} type="button">
            {installed
              ? t(key("install.installed"))
              : active
                ? t(projectMarketPhaseLabel(namespace, operation?.phase))
                : t(key("install.download"))}
          </button>
        </footer>
      </div>
    </article>
  );
}

function projectMarketPhaseLabel(
  namespace: ProjectMarketNamespace,
  phase: ProjectMarketInstallOperation["phase"] | undefined,
): TranslationKey {
  const suffix = phase === "downloading"
    ? "downloading"
    : phase === "extracting"
      ? "extracting"
      : phase === "importing"
        ? "importing"
        : "queued";
  return `${namespace}.install.phases.${suffix}` as TranslationKey;
}

function formatDate(value: string, language: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(language, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}
