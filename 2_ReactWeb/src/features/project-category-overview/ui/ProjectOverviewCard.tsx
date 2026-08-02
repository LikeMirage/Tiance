import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  CornersIn,
  CornersOut,
  FolderOpen,
  GitBranch,
  NotePencil,
  X,
} from "@phosphor-icons/react";

import type {
  ProjectOverviewItem,
  ProjectOverviewUsage,
} from "../../../entities/project/model/project";
import {
  formatCostAmount,
  formatTokenCount,
} from "../../../shared/model/usageFormatting";
import { useI18n } from "../../../shared/i18n";
import {
  formatProjectCreatedAt,
  resolveEnterSessionId,
} from "../model/projectOverviewDisplay";
import {
  getDisplaySessionUsage,
  mergeProjectOverviewUsage,
  sumLiveUsageForProject,
  type LiveUsageBySessionKey,
  type ProjectOverviewSessionWithDisplayUsage,
} from "../model/projectOverviewUsage";
import { buildProjectOverviewSessionTree } from "../model/projectOverviewSessionTree";
import { ProjectOverviewSessionTreeList } from "./ProjectOverviewSessionTree";

type ProjectOverviewCardProps = {
  creating: boolean;
  isMaximized: boolean;
  item: ProjectOverviewItem;
  liveUsageBySessionKey: LiveUsageBySessionKey;
  onCreateSession: (projectId: string) => Promise<void>;
  onEnterSession: (projectId: string, sessionId: string) => Promise<void>;
  onOpenSessionContextMenu: (
    projectId: string,
    session: ProjectOverviewSessionWithDisplayUsage,
    position: { x: number; y: number },
  ) => void;
  onOpenConversationBranches: (projectId: string, sessionId: string | null) => Promise<void>;
  onCancelSessionRename: () => void;
  onCommitSessionRename: (nextTitle: string) => Promise<void>;
  onPrepareProject?: (projectId: string) => void;
  onRevealProject: (projectId: string) => Promise<void>;
  onSelectSession: (projectId: string, sessionId: string) => Promise<void>;
  renameError: string | null;
  renamingSessionBusy: boolean;
  renamingSessionId: string | null;
  onCloseUsage: () => void;
  onToggleUsage: () => void;
  onToggleMaximized: () => void;
  usageOpen: boolean;
  visibleSession: { projectId: string; sessionId: string | null } | null;
  showMaximizeAction?: boolean;
};

export function ProjectOverviewCard({
  creating,
  isMaximized,
  item,
  onCreateSession,
  onEnterSession,
  onOpenSessionContextMenu,
  onOpenConversationBranches,
  onCancelSessionRename,
  onCommitSessionRename,
  onPrepareProject,
  onRevealProject,
  onSelectSession,
  renameError,
  renamingSessionBusy,
  renamingSessionId,
  onCloseUsage,
  onToggleUsage,
  onToggleMaximized,
  liveUsageBySessionKey,
  usageOpen,
  visibleSession,
  showMaximizeAction = true,
}: ProjectOverviewCardProps) {
  const { language, t } = useI18n();
  const projectId = item.project.project_id;
  const usageAreaRef = useRef<HTMLDivElement | null>(null);
  const usagePopoverRef = useRef<HTMLDivElement | null>(null);
  const [isRevealingProject, setIsRevealingProject] = useState(false);
  const [selectedUsageSessionId, setSelectedUsageSessionId] = useState<string | null>(null);
  const sessions = item.sessions;
  const displaySessions = useMemo(
    () => sessions.map((session) => ({
      ...session,
      displayUsage: getDisplaySessionUsage(projectId, session, liveUsageBySessionKey),
    })),
    [liveUsageBySessionKey, projectId, sessions],
  );
  const sessionTree = useMemo(
    () => buildProjectOverviewSessionTree(
      displaySessions,
      item.session_relations ?? [],
    ),
    [displaySessions, item.session_relations],
  );
  const displayProjectUsage = useMemo(
    () => mergeProjectOverviewUsage(
      item.usage,
      sumLiveUsageForProject(projectId, sessions, liveUsageBySessionKey),
    ),
    [item.usage, liveUsageBySessionKey, projectId, sessions],
  );
  const visibleSessionId =
    visibleSession?.projectId === projectId ? visibleSession.sessionId : null;
  const isCurrentProject = visibleSession?.projectId === projectId;
  const enterSessionId = resolveEnterSessionId(
    sessions,
    visibleSessionId,
    item.active_session_id,
  );

  useEffect(() => {
    if (!usageOpen) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        (
          usageAreaRef.current?.contains(target) ||
          usagePopoverRef.current?.contains(target)
        )
      ) return;
      onCloseUsage();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseUsage();
      }
    };
    window.addEventListener("pointerdown", handlePointerDown, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onCloseUsage, usageOpen]);

  return (
    <article
      className={[
        "project-category-overview__card",
        isCurrentProject ? "project-category-overview__card--active" : "",
      ].filter(Boolean).join(" ")}
      aria-current={isCurrentProject ? "true" : undefined}
      onFocusCapture={() => onPrepareProject?.(projectId)}
      onPointerEnter={() => onPrepareProject?.(projectId)}
    >
      <header className="project-category-overview__card-header">
        <div className="project-category-overview__card-title-group">
          <h3 className="project-category-overview__project-name" title={item.project.name}>
            <button
              className="project-category-overview__project-title-button"
              type="button"
              disabled={!enterSessionId}
              title={enterSessionId
                ? t("projectOverview.card.enterCurrentSession")
                : t("projectOverview.card.noSessionToEnter")}
              onClick={() => {
                if (!enterSessionId) return;
                void onEnterSession(projectId, enterSessionId);
              }}
            >
              {item.project.name}
            </button>
          </h3>
        </div>
        <div className="project-category-overview__card-actions">
          <button
            className="project-category-overview__card-action"
            type="button"
            aria-label={t("projectOverview.card.revealInExplorer")}
            title={t("projectOverview.card.revealInExplorer")}
            disabled={isRevealingProject}
            onClick={() => {
              setIsRevealingProject(true);
              void onRevealProject(projectId)
                .catch(() => undefined)
                .finally(() => {
                  setIsRevealingProject((current) => current ? false : current);
                });
            }}
          >
            <FolderOpen size={15} weight="regular" aria-hidden="true" />
          </button>
          <button
            className="project-category-overview__card-action"
            type="button"
            aria-label={t("projectOverview.views.branches")}
            title={t("projectOverview.views.branches")}
            onClick={() => void onOpenConversationBranches(projectId, enterSessionId)}
          >
            <GitBranch size={15} weight="regular" aria-hidden="true" />
          </button>
          <button
            className="project-category-overview__card-action"
            type="button"
            aria-label={t("projectOverview.card.createSession")}
            title={t("projectOverview.card.createSession")}
            disabled={creating}
            onClick={() => void onCreateSession(projectId)}
          >
            <NotePencil size={15} weight="regular" aria-hidden="true" />
          </button>
          {showMaximizeAction ? (
            <button
              className="project-category-overview__card-action"
              type="button"
              aria-label={t(
                isMaximized
                  ? "projectOverview.card.restore"
                  : "projectOverview.card.maximize",
              )}
              title={t(
                isMaximized
                  ? "projectOverview.card.restore"
                  : "projectOverview.card.maximize",
              )}
              aria-pressed={isMaximized}
              onClick={onToggleMaximized}
            >
              {isMaximized ? (
                <CornersIn size={15} weight="regular" aria-hidden="true" />
              ) : (
                <CornersOut size={15} weight="regular" aria-hidden="true" />
              )}
            </button>
          ) : null}
        </div>
      </header>

      <div className="project-category-overview__sessions" aria-label={t("projectOverview.card.sessionsAria")}>
        {displaySessions.length > 0 ? (
          <ProjectOverviewSessionTreeList
            activeSessionId={visibleSessionId}
            onCancelSessionRename={onCancelSessionRename}
            onCommitSessionRename={onCommitSessionRename}
            onOpenSessionContextMenu={(session, position) =>
              onOpenSessionContextMenu(projectId, session, position)}
            onSelectSession={(sessionId) => onSelectSession(projectId, sessionId)}
            renameError={renameError}
            renamingSessionBusy={renamingSessionBusy}
            renamingSessionId={renamingSessionId}
            tree={sessionTree}
          />
        ) : (
          <div className="project-category-overview__empty-session">
            {t("projectOverview.card.emptySessions")}
          </div>
        )}
      </div>

      <footer className="project-category-overview__card-footer">
        <span className="project-category-overview__card-created">
          {formatProjectCreatedAt(
            item.project.created_at,
            language,
            t("projectOverview.card.createdUnknown"),
          )}
        </span>
        <div className="project-category-overview__usage-area" ref={usageAreaRef}>
          <span className="project-category-overview__card-session-count">
            {t("projectOverview.sessionCount", {
              count: displaySessions.length,
            })}
          </span>
          <button
            className="project-category-overview__usage-trigger"
            type="button"
            aria-expanded={usageOpen}
            onClick={onToggleUsage}
          >
            Tokens {formatTokenCount(displayProjectUsage.total_tokens)}
          </button>
          {usageOpen ? (
            <ProjectUsagePopoverPortal
              anchorRef={usageAreaRef}
              popoverRef={usagePopoverRef}
              projectUsage={displayProjectUsage}
              sessions={displaySessions}
              selectedSessionId={selectedUsageSessionId}
              onClose={onCloseUsage}
              onSelectSessionId={setSelectedUsageSessionId}
            />
          ) : null}
        </div>
      </footer>
    </article>
  );
}
function ProjectUsagePopoverPortal({
  anchorRef,
  popoverRef,
  ...popoverProps
}: {
  anchorRef: RefObject<HTMLDivElement | null>;
  popoverRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onSelectSessionId: (sessionId: string | null) => void;
  projectUsage: ProjectOverviewUsage;
  selectedSessionId: string | null;
  sessions: ProjectOverviewSessionWithDisplayUsage[];
}) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const updatePosition = () => {
      const anchor = anchorRef.current;
      const popover = popoverRef.current;
      if (!anchor || !popover) return;

      const viewportPadding = 8;
      const gap = 8;
      const anchorRect = anchor.getBoundingClientRect();
      const popoverRect = popover.getBoundingClientRect();
      const maxLeft = Math.max(
        viewportPadding,
        window.innerWidth - popoverRect.width - viewportPadding,
      );
      const maxTop = Math.max(
        viewportPadding,
        window.innerHeight - popoverRect.height - viewportPadding,
      );
      const preferredTop = anchorRect.top - popoverRect.height - gap;
      const fallbackTop = Math.min(anchorRect.bottom + gap, maxTop);

      setPosition({
        left: Math.max(
          viewportPadding,
          Math.min(anchorRect.right - popoverRect.width, maxLeft),
        ),
        top: Math.max(
          viewportPadding,
          preferredTop >= viewportPadding ? preferredTop : fallbackTop,
        ),
      });
    };

    updatePosition();
    const frame = window.requestAnimationFrame(updatePosition);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [
    anchorRef,
    popoverProps.selectedSessionId,
    popoverProps.sessions.length,
    popoverRef,
  ]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <ProjectUsagePopover
      {...popoverProps}
      popoverRef={popoverRef}
      position={position}
    />,
    document.body,
  );
}
function ProjectUsagePopover({
  onClose,
  onSelectSessionId,
  popoverRef,
  position,
  projectUsage,
  selectedSessionId,
  sessions,
}: {
  onClose: () => void;
  onSelectSessionId: (sessionId: string | null) => void;
  popoverRef: RefObject<HTMLDivElement | null>;
  position: { left: number; top: number } | null;
  projectUsage: ProjectOverviewUsage;
  selectedSessionId: string | null;
  sessions: ProjectOverviewSessionWithDisplayUsage[];
}) {
  const { t } = useI18n();
  const selectedSession = selectedSessionId
    ? sessions.find((session) => session.session_id === selectedSessionId) ?? null
    : null;
  const selectedUsage = selectedSession?.displayUsage ?? projectUsage;
  return (
    <div
      ref={popoverRef}
      className="project-category-overview__usage-popover"
      role="dialog"
      aria-label={t("projectOverview.usage.title")}
      style={{
        left: position ? `${position.left}px` : "0",
        top: position ? `${position.top}px` : "0",
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="project-category-overview__usage-popover-head">
        <span>{t("projectOverview.usage.title")}</span>
        <button
          className="project-category-overview__usage-close"
          type="button"
          aria-label={t("projectOverview.usage.closeAria")}
          title={t("common.actions.close")}
          onClick={onClose}
        >
          <X size={12} weight="bold" aria-hidden="true" />
        </button>
      </div>
      <div className="project-category-overview__usage-layout">
        <div className="project-category-overview__usage-scope-list" role="listbox">
          <button
            className="project-category-overview__usage-scope-option"
            type="button"
            aria-selected={selectedSessionId === null}
            onClick={() => onSelectSessionId(null)}
          >
            <span className="project-category-overview__usage-scope-main">
              <span className="project-category-overview__usage-scope-title">
                {t("projectOverview.usage.allTotal")}
              </span>
              <span className="project-category-overview__usage-scope-meta">
                {t("projectOverview.sessionCount", { count: sessions.length })}
              </span>
            </span>
            <span className="project-category-overview__usage-scope-tokens">
              {formatTokenCount(projectUsage.total_tokens)}
            </span>
          </button>
          {sessions.map((session) => (
            <button
              key={session.session_id}
              className="project-category-overview__usage-scope-option"
              type="button"
              aria-selected={selectedSessionId === session.session_id}
              onClick={() => onSelectSessionId(session.session_id)}
            >
              <span className="project-category-overview__usage-scope-main">
                <span className="project-category-overview__usage-scope-title">
                  {session.sequence_number}. {session.title.trim() || t("projectOverview.newConversation")}
                </span>
              </span>
              <span
                className="project-category-overview__usage-scope-tokens"
                title={t("projectOverview.usage.sessionTotalTitle", {
                  value: formatTokenCount(session.displayUsage.total_tokens),
                })}
              >
                {formatTokenCount(session.displayUsage.total_tokens)}
              </span>
            </button>
          ))}
        </div>
        <ProjectUsageMetricGrid usage={selectedUsage} />
      </div>
    </div>
  );
}

function ProjectUsageMetricGrid({ usage }: { usage: ProjectOverviewUsage }) {
  const { t } = useI18n();

  return (
    <dl className="project-category-overview__usage-grid">
      <div>
        <dt>{t("projectOverview.usage.metrics.total")}</dt>
        <dd>{formatTokenCount(usage.total_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.input")}</dt>
        <dd>{formatTokenCount(usage.prompt_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.output")}</dt>
        <dd>{formatTokenCount(usage.completion_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.reasoning")}</dt>
        <dd>{formatTokenCount(usage.reasoning_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.cacheHit")}</dt>
        <dd>{formatTokenCount(usage.prompt_cache_hit_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.cacheMiss")}</dt>
        <dd>{formatTokenCount(usage.prompt_cache_miss_tokens)}</dd>
      </div>
      <div>
        <dt>{t("projectOverview.usage.metrics.cost")}</dt>
        <dd>{formatCostAmount(usage)}</dd>
      </div>
    </dl>
  );
}
