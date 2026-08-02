import {
  CaretDown,
  CaretRight,
  Check,
  PushPin,
} from "@phosphor-icons/react";
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";

import { useI18n } from "../../../shared/i18n";
import { formatTokenCount } from "../../../shared/model/usageFormatting";
import {
  collectSessionAncestorIds,
  PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS,
  PROJECT_OVERVIEW_SESSION_GROUPS,
  type ProjectOverviewSessionGroup,
  type ProjectOverviewSessionTree,
  type ProjectOverviewSessionTreeNode,
} from "../model/projectOverviewSessionTree";
import type { ProjectOverviewSessionWithDisplayUsage } from "../model/projectOverviewUsage";
import { normalizeRuntimeStatus } from "../model/projectOverviewDisplay";

type ProjectOverviewSessionTreeProps = {
  activeSessionId: string | null;
  onCancelSessionRename: () => void;
  onCommitSessionRename: (nextTitle: string) => Promise<void>;
  onOpenSessionContextMenu: (
    session: ProjectOverviewSessionWithDisplayUsage,
    position: { x: number; y: number },
  ) => void;
  onSelectSession: (sessionId: string) => Promise<void>;
  renameError: string | null;
  renamingSessionBusy: boolean;
  renamingSessionId: string | null;
  tree: ProjectOverviewSessionTree;
};

type SessionDepthStyle = CSSProperties & {
  "--project-overview-session-indent": string;
};

const SESSION_GROUP_LABEL_KEYS = {
  branch: "projectOverview.card.branchGroup",
  child: "projectOverview.card.childSessionGroup",
  automaticNaming: "projectOverview.card.automaticNamingGroup",
  globalMemoryManagement:
    "projectOverview.card.globalMemoryManagementGroup",
  memoryCompaction: "projectOverview.card.memoryCompactionGroup",
  projectMemoryManagement:
    "projectOverview.card.projectMemoryManagementGroup",
} as const satisfies Record<
  Exclude<ProjectOverviewSessionGroup, "functional">,
  string
>;

function sessionGroupKey(
  parentSessionId: string,
  group: ProjectOverviewSessionGroup,
) {
  return `${parentSessionId}:${group}`;
}

export function ProjectOverviewSessionTreeList({
  activeSessionId,
  onCancelSessionRename,
  onCommitSessionRename,
  onOpenSessionContextMenu,
  onSelectSession,
  renameError,
  renamingSessionBusy,
  renamingSessionId,
  tree,
}: ProjectOverviewSessionTreeProps) {
  const [expandedSessionIds, setExpandedSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const activeSessionElementRef = useRef<HTMLDivElement | null>(null);
  const pendingRevealSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    pendingRevealSessionIdRef.current = activeSessionId;
    if (!activeSessionId) return;
    const ancestors = collectSessionAncestorIds(
      activeSessionId,
      tree.parentSessionIdBySession,
    );
    if (ancestors.length === 0) return;
    setExpandedSessionIds((current) => {
      if (ancestors.every((sessionId) => current.has(sessionId))) {
        return current;
      }
      const next = new Set(current);
      ancestors.forEach((sessionId) => next.add(sessionId));
      return next;
    });
    setExpandedGroupKeys((current) => {
      const next = new Set(current);
      let childSessionId: string | undefined = activeSessionId;
      while (childSessionId) {
        const parentSessionId =
          tree.parentSessionIdBySession.get(childSessionId);
        const parentGroup = tree.parentGroupBySession.get(childSessionId);
        if (!parentSessionId || !parentGroup) break;
        next.add(sessionGroupKey(parentSessionId, parentGroup));
        if (isFunctionSessionGroup(parentGroup)) {
          next.add(sessionGroupKey(parentSessionId, "functional"));
        }
        childSessionId = parentSessionId;
      }
      return next.size === current.size ? current : next;
    });
  }, [
    activeSessionId,
    tree.parentGroupBySession,
    tree.parentSessionIdBySession,
  ]);

  useEffect(() => {
    if (
      !activeSessionId
      || pendingRevealSessionIdRef.current !== activeSessionId
    ) {
      return undefined;
    }
    const activeElement = activeSessionElementRef.current;
    const scrollContainer = activeElement?.closest<HTMLElement>(
      ".project-category-overview__sessions",
    );
    if (!activeElement || !scrollContainer) return undefined;

    let animationFrame = 0;
    let resizeObserver: ResizeObserver | null = null;
    const revealWhenVisible = () => {
      if (
        pendingRevealSessionIdRef.current !== activeSessionId
        || scrollContainer.clientHeight <= 0
      ) {
        return;
      }
      const activeRect = activeElement.getBoundingClientRect();
      const containerRect = scrollContainer.getBoundingClientRect();
      if (activeRect.top < containerRect.top) {
        scrollContainer.scrollTop += activeRect.top - containerRect.top;
      } else if (activeRect.bottom > containerRect.bottom) {
        scrollContainer.scrollTop += activeRect.bottom - containerRect.bottom;
      }
      pendingRevealSessionIdRef.current = null;
      resizeObserver?.disconnect();
    };

    animationFrame = window.requestAnimationFrame(revealWhenVisible);
    resizeObserver = new ResizeObserver(revealWhenVisible);
    resizeObserver.observe(scrollContainer);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
    };
  }, [activeSessionId, expandedGroupKeys, expandedSessionIds]);

  const toggleSession = (sessionId: string) => {
    setExpandedSessionIds((current) => {
      const next = new Set(current);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const toggleGroup = (
    parentSessionId: string,
    group: ProjectOverviewSessionGroup,
  ) => {
    const key = sessionGroupKey(parentSessionId, group);
    setExpandedGroupKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return tree.roots.map((node) => (
    <ProjectOverviewSessionTreeItem
      key={node.session.session_id}
      activeSessionId={activeSessionId}
      activeSessionElementRef={activeSessionElementRef}
      depth={0}
      expandedGroupKeys={expandedGroupKeys}
      expandedSessionIds={expandedSessionIds}
      node={node}
      onCancelSessionRename={onCancelSessionRename}
      onCommitSessionRename={onCommitSessionRename}
      onOpenSessionContextMenu={onOpenSessionContextMenu}
      onSelectSession={onSelectSession}
      onToggleGroup={toggleGroup}
      onToggleSession={toggleSession}
      renameError={renameError}
      renamingSessionBusy={renamingSessionBusy}
      renamingSessionId={renamingSessionId}
    />
  ));
}

function ProjectOverviewSessionTreeItem({
  activeSessionId,
  activeSessionElementRef,
  depth,
  expandedGroupKeys,
  expandedSessionIds,
  node,
  onCancelSessionRename,
  onCommitSessionRename,
  onOpenSessionContextMenu,
  onSelectSession,
  onToggleGroup,
  onToggleSession,
  renameError,
  renamingSessionBusy,
  renamingSessionId,
}: {
  activeSessionId: string | null;
  activeSessionElementRef: RefObject<HTMLDivElement | null>;
  depth: number;
  expandedGroupKeys: ReadonlySet<string>;
  expandedSessionIds: ReadonlySet<string>;
  node: ProjectOverviewSessionTreeNode;
  onCancelSessionRename: () => void;
  onCommitSessionRename: (nextTitle: string) => Promise<void>;
  onOpenSessionContextMenu: (
    session: ProjectOverviewSessionWithDisplayUsage,
    position: { x: number; y: number },
  ) => void;
  onSelectSession: (sessionId: string) => Promise<void>;
  onToggleGroup: (
    parentSessionId: string,
    group: ProjectOverviewSessionGroup,
  ) => void;
  onToggleSession: (sessionId: string) => void;
  renameError: string | null;
  renamingSessionBusy: boolean;
  renamingSessionId: string | null;
}) {
  const { t } = useI18n();
  const session = node.session;
  const sessionId = session.session_id;
  const title = session.title.trim() || t("projectOverview.newConversation");
  const normalizedStatus = normalizeRuntimeStatus(session.runtime_status);
  const isActive = activeSessionId === sessionId;
  const isExpanded = expandedSessionIds.has(sessionId);
  const isRenaming = renamingSessionId === sessionId;
  const depthStyle: SessionDepthStyle = {
    "--project-overview-session-indent": `${depth * 12}px`,
  };
  const handleSessionClick = () => {
    if (isActive) {
      onToggleSession(sessionId);
      return;
    }
    void onSelectSession(sessionId);
  };

  return (
    <>
      <div
        ref={isActive ? activeSessionElementRef : undefined}
        className={[
          "project-category-overview__session",
          depth > 0 ? "project-category-overview__session--nested" : "",
          isRenaming ? "project-category-overview__session--renaming" : "",
          `project-category-overview__session--${normalizedStatus}`,
          isActive ? "project-category-overview__session--active" : "",
        ].filter(Boolean).join(" ")}
        style={depthStyle}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onOpenSessionContextMenu(session, {
            x: event.clientX,
            y: event.clientY,
          });
        }}
      >
        {isRenaming ? (
          <div className="project-category-overview__session-main">
            <SessionSequence sequenceNumber={session.sequence_number} />
            <StatusDot status={normalizedStatus} />
            <SessionInlineRename
              busy={renamingSessionBusy}
              defaultValue={title}
              error={renameError}
              onCancel={onCancelSessionRename}
              onCommit={onCommitSessionRename}
            />
            <SessionUsage session={session} />
          </div>
        ) : (
          <button
            className="project-category-overview__session-main"
            type="button"
            aria-expanded={isExpanded}
            onClick={handleSessionClick}
          >
            <SessionSequence sequenceNumber={session.sequence_number} />
            <StatusDot status={normalizedStatus} />
            <span className="project-category-overview__session-title">
              {session.pinned ? (
                <PushPin
                  className="project-category-overview__session-pin"
                  size={12}
                  weight="fill"
                  aria-hidden="true"
                />
              ) : null}
              <span className="project-category-overview__session-title-text">
                {title}
              </span>
            </span>
            <SessionUsage session={session} />
          </button>
        )}
        <button
          className="project-category-overview__session-toggle"
          type="button"
          aria-expanded={isExpanded}
          aria-label={t(
            isExpanded
              ? "projectOverview.card.collapseSession"
              : "projectOverview.card.expandSession",
            { title },
          )}
          title={t(
            isExpanded
              ? "projectOverview.card.collapseSession"
              : "projectOverview.card.expandSession",
            { title },
          )}
          onClick={handleSessionClick}
        >
          {isExpanded ? (
            <CaretDown size={13} weight="bold" aria-hidden="true" />
          ) : (
            <CaretRight size={13} weight="bold" aria-hidden="true" />
          )}
        </button>
      </div>
      {isExpanded ? (
        <>
          {PROJECT_OVERVIEW_SESSION_GROUPS.map((group) => {
            const children = node.childrenByGroup[group];
            const groupExpanded = expandedGroupKeys.has(
              sessionGroupKey(sessionId, group),
            );
            return (
              <Fragment key={group}>
                <SessionGroupHeader
                  count={children.length}
                  depth={depth + 1}
                  expanded={groupExpanded}
                  label={t(SESSION_GROUP_LABEL_KEYS[group])}
                  onToggle={() => onToggleGroup(sessionId, group)}
                />
                {groupExpanded ? (
                  children.length > 0 ? (
                    children.map((child) => (
                      <ProjectOverviewSessionTreeItem
                        key={child.session.session_id}
                        activeSessionId={activeSessionId}
                        activeSessionElementRef={activeSessionElementRef}
                        depth={depth + 1}
                        expandedGroupKeys={expandedGroupKeys}
                        expandedSessionIds={expandedSessionIds}
                        node={child}
                        onCancelSessionRename={onCancelSessionRename}
                        onCommitSessionRename={onCommitSessionRename}
                        onOpenSessionContextMenu={onOpenSessionContextMenu}
                        onSelectSession={onSelectSession}
                        onToggleGroup={onToggleGroup}
                        onToggleSession={onToggleSession}
                        renameError={renameError}
                        renamingSessionBusy={renamingSessionBusy}
                        renamingSessionId={renamingSessionId}
                      />
                    ))
                  ) : (
                    <EmptySessionGroup depth={depth + 1} />
                  )
                ) : null}
              </Fragment>
            );
          })}
          <FunctionalSessionGroups
            activeSessionElementRef={activeSessionElementRef}
            activeSessionId={activeSessionId}
            depth={depth}
            expandedGroupKeys={expandedGroupKeys}
            expandedSessionIds={expandedSessionIds}
            node={node}
            onCancelSessionRename={onCancelSessionRename}
            onCommitSessionRename={onCommitSessionRename}
            onOpenSessionContextMenu={onOpenSessionContextMenu}
            onSelectSession={onSelectSession}
            onToggleGroup={onToggleGroup}
            onToggleSession={onToggleSession}
            renameError={renameError}
            renamingSessionBusy={renamingSessionBusy}
            renamingSessionId={renamingSessionId}
          />
        </>
      ) : null}
    </>
  );
}

function FunctionalSessionGroups({
  activeSessionElementRef,
  activeSessionId,
  depth,
  expandedGroupKeys,
  expandedSessionIds,
  node,
  onCancelSessionRename,
  onCommitSessionRename,
  onOpenSessionContextMenu,
  onSelectSession,
  onToggleGroup,
  onToggleSession,
  renameError,
  renamingSessionBusy,
  renamingSessionId,
}: {
  activeSessionElementRef: RefObject<HTMLDivElement | null>;
  activeSessionId: string | null;
  depth: number;
  expandedGroupKeys: ReadonlySet<string>;
  expandedSessionIds: ReadonlySet<string>;
  node: ProjectOverviewSessionTreeNode;
  onCancelSessionRename: () => void;
  onCommitSessionRename: (nextTitle: string) => Promise<void>;
  onOpenSessionContextMenu: (
    session: ProjectOverviewSessionWithDisplayUsage,
    position: { x: number; y: number },
  ) => void;
  onSelectSession: (sessionId: string) => Promise<void>;
  onToggleGroup: (
    parentSessionId: string,
    group: ProjectOverviewSessionGroup,
  ) => void;
  onToggleSession: (sessionId: string) => void;
  renameError: string | null;
  renamingSessionBusy: boolean;
  renamingSessionId: string | null;
}) {
  const { t } = useI18n();
  const sessionId = node.session.session_id;
  const functionalExpanded = expandedGroupKeys.has(
    sessionGroupKey(sessionId, "functional"),
  );
  const count = PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS.reduce(
    (total, group) => total + node.childrenByGroup[group].length,
    0,
  );
  return (
    <>
      <SessionGroupHeader
        count={count}
        depth={depth + 1}
        expanded={functionalExpanded}
        label={t("projectOverview.card.functionalSessionGroup")}
        onToggle={() => onToggleGroup(sessionId, "functional")}
      />
      {functionalExpanded
        ? PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS.map((group) => {
            const children = node.childrenByGroup[group];
            const expanded = expandedGroupKeys.has(
              sessionGroupKey(sessionId, group),
            );
            return (
              <Fragment key={group}>
                <SessionGroupHeader
                  count={children.length}
                  depth={depth + 2}
                  expanded={expanded}
                  label={t(SESSION_GROUP_LABEL_KEYS[group])}
                  onToggle={() => onToggleGroup(sessionId, group)}
                />
                {expanded ? (
                  children.length > 0 ? (
                    children.map((child) => (
                      <ProjectOverviewSessionTreeItem
                        key={child.session.session_id}
                        activeSessionElementRef={activeSessionElementRef}
                        activeSessionId={activeSessionId}
                        depth={depth + 2}
                        expandedGroupKeys={expandedGroupKeys}
                        expandedSessionIds={expandedSessionIds}
                        node={child}
                        onCancelSessionRename={onCancelSessionRename}
                        onCommitSessionRename={onCommitSessionRename}
                        onOpenSessionContextMenu={onOpenSessionContextMenu}
                        onSelectSession={onSelectSession}
                        onToggleGroup={onToggleGroup}
                        onToggleSession={onToggleSession}
                        renameError={renameError}
                        renamingSessionBusy={renamingSessionBusy}
                        renamingSessionId={renamingSessionId}
                      />
                    ))
                  ) : (
                    <EmptySessionGroup depth={depth + 2} />
                  )
                ) : null}
              </Fragment>
            );
          })
        : null}
    </>
  );
}

function isFunctionSessionGroup(
  group: ProjectOverviewSessionGroup,
): boolean {
  return PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS.includes(
    group as (typeof PROJECT_OVERVIEW_FUNCTION_SESSION_GROUPS)[number],
  );
}

function SessionGroupHeader({
  count,
  depth,
  expanded,
  label,
  onToggle,
}: {
  count: number;
  depth: number;
  expanded: boolean;
  label: string;
  onToggle: () => void;
}) {
  const style: SessionDepthStyle = {
    "--project-overview-session-indent": `${depth * 12}px`,
  };
  return (
    <button
      className="project-category-overview__session-group"
      type="button"
      aria-expanded={expanded}
      style={style}
      onClick={onToggle}
    >
      <span className="project-category-overview__session-group-label">
        {expanded ? (
          <CaretDown size={12} weight="bold" aria-hidden="true" />
        ) : (
          <CaretRight size={12} weight="bold" aria-hidden="true" />
        )}
        <span>{label}</span>
      </span>
      <span>{count}</span>
    </button>
  );
}

function EmptySessionGroup({ depth }: { depth: number }) {
  const { t } = useI18n();
  const style: SessionDepthStyle = {
    "--project-overview-session-indent": `${depth * 12}px`,
  };
  return (
    <div className="project-category-overview__session-group-empty" style={style}>
      {t("projectOverview.card.emptySessionGroup")}
    </div>
  );
}

function SessionSequence({ sequenceNumber }: { sequenceNumber: number }) {
  return (
    <span className="project-category-overview__session-sequence">
      {sequenceNumber}
    </span>
  );
}

function SessionUsage({
  session,
}: {
  session: ProjectOverviewSessionWithDisplayUsage;
}) {
  return (
    <span
      className="project-category-overview__session-usage"
      title={formatTokenCount(session.displayUsage.total_tokens)}
    >
      {formatTokenCount(session.displayUsage.total_tokens)}
    </span>
  );
}

function SessionInlineRename({
  busy,
  defaultValue,
  error,
  onCancel,
  onCommit,
}: {
  busy: boolean;
  defaultValue: string;
  error: string | null;
  onCancel: () => void;
  onCommit: (nextTitle: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const committingRef = useRef(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const commit = async (nextTitle: string) => {
    if (committingRef.current || busy) return;
    committingRef.current = true;
    try {
      await onCommit(nextTitle);
    } finally {
      committingRef.current = false;
    }
  };

  return (
    <span className="project-category-overview__session-rename-field">
      <span className="project-category-overview__session-rename-control">
        <input
          ref={inputRef}
          className="project-category-overview__session-rename-input"
          defaultValue={defaultValue}
          disabled={busy}
          onBlur={(event) => {
            void commit(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void commit(event.currentTarget.value);
            } else if (event.key === "Escape") {
              event.preventDefault();
              onCancel();
            }
          }}
        />
        <button
          className="project-category-overview__session-rename-save"
          type="button"
          aria-label={t("projectOverview.card.saveSessionName")}
          disabled={busy}
          onMouseDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          onClick={(event) => {
            event.stopPropagation();
            void commit(inputRef.current?.value ?? defaultValue);
          }}
        >
          <Check
            className="project-category-overview__session-rename-save-glyph"
            weight="bold"
          />
        </button>
      </span>
      {error ? (
        <span className="project-category-overview__session-rename-error">
          {error}
        </span>
      ) : null}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const normalized = normalizeRuntimeStatus(status);
  return (
    <span
      className={`project-category-overview__status-dot project-category-overview__status-dot--${normalized}`}
      aria-hidden="true"
    />
  );
}
