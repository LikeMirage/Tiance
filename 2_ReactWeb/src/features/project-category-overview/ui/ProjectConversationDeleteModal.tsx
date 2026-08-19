import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import type {
  ConversationBranchNode,
  ConversationSession,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { getProjectConversations } from "../../../services/project/getProjectConversations";

import "./project-conversation-delete-modal.css";

type DeleteTreeNode = {
  children: DeleteTreeNode[];
  sessionId: string;
  title: string;
};

type ProjectConversationDeleteModalProps = {
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (sessionIds: string[]) => void;
  projectId: string;
  sessionId: string;
  title: string;
};

export function ProjectConversationDeleteModal({
  busy,
  error,
  onCancel,
  onConfirm,
  projectId,
  sessionId,
  title,
}: ProjectConversationDeleteModalProps) {
  const { t } = useI18n();
  const [tree, setTree] = useState<DeleteTreeNode[]>([]);
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(
    () => new Set([sessionId]),
  );
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    setSelectedSessionIds(new Set([sessionId]));
    void getProjectConversations(projectId, controller.signal)
      .then((response) => {
        setTree(buildDeleteTree(response, sessionId, title));
      })
      .catch((loadFailure) => {
        if (controller.signal.aborted) return;
        setLoadError(
          loadFailure instanceof Error
            ? loadFailure.message
            : t("projectOverview.deleteSessionTreeLoadFailed"),
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, sessionId, t, title]);

  return (
    <ConfirmModal
      cancelDisabled={busy}
      confirmDisabled={busy || loading || Boolean(loadError)}
      confirmLabel={busy
        ? t("projectOverview.deleteSessionDeleting")
        : t("common.actions.delete")}
      danger
      dialogClassName="project-conversation-delete-modal"
      message={t("projectOverview.deleteSessionMessage", { title })}
      onCancel={onCancel}
      onConfirm={() => onConfirm(Array.from(selectedSessionIds))}
      title={t("projectOverview.deleteSessionTitle")}
    >
      {loading ? (
        <p className="project-conversation-delete-modal__status">
          {t("projectOverview.deleteSessionTreeLoading")}
        </p>
      ) : null}

      {!loading && tree.length > 0 ? (
        <>
          <div className="project-conversation-delete-modal__tree">
            {tree.map((node) => (
              <DeleteTreeItem
                key={node.sessionId}
                busy={busy}
                defaultExpanded={node.sessionId === sessionId}
                locked={node.sessionId === sessionId}
                node={node}
                selectedSessionIds={selectedSessionIds}
                setSelectedSessionIds={setSelectedSessionIds}
              />
            ))}
          </div>
          <p className="project-conversation-delete-modal__summary">
            {t("projectOverview.deleteSessionSelectionSummary", {
              count: selectedSessionIds.size,
            })}
          </p>
        </>
      ) : null}

      {loadError || error ? (
        <p className="project-category-overview__session-action-error" role="alert">
          {loadError ?? error}
        </p>
      ) : null}
    </ConfirmModal>
  );
}

type DeleteTreeItemProps = {
  busy: boolean;
  defaultExpanded?: boolean;
  locked?: boolean;
  node: DeleteTreeNode;
  selectedSessionIds: Set<string>;
  setSelectedSessionIds: Dispatch<SetStateAction<Set<string>>>;
};

function DeleteTreeItem({
  busy,
  defaultExpanded = false,
  locked = false,
  node,
  selectedSessionIds,
  setSelectedSessionIds,
}: DeleteTreeItemProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const subtreeSessionIds = useMemo(() => [
    node.sessionId,
    ...collectTreeSessionIds(node.children),
  ], [node]);
  const selectedCount = subtreeSessionIds.reduce(
    (count, subtreeSessionId) => (
      count + (selectedSessionIds.has(subtreeSessionId) ? 1 : 0)
    ),
    0,
  );
  const checkboxRef = useRef<HTMLInputElement>(null);
  const checked = selectedCount === subtreeSessionIds.length;
  const indeterminate = selectedCount > 0 && !checked;

  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <div className="project-conversation-delete-modal__tree-node">
      <div className="project-conversation-delete-modal__tree-row">
        {node.children.length > 0 ? (
          <button
            aria-expanded={expanded}
            aria-label={t(expanded
              ? "projectOverview.deleteSessionCollapseBranch"
              : "projectOverview.deleteSessionExpandBranch")}
            className="project-conversation-delete-modal__tree-toggle"
            disabled={busy}
            onClick={() => setExpanded((current) => !current)}
            type="button"
          >
            <span aria-hidden="true" />
          </button>
        ) : (
          <span
            aria-hidden="true"
            className="project-conversation-delete-modal__tree-toggle-spacer"
          />
        )}
        <label>
          <input
            ref={checkboxRef}
            checked={checked}
            disabled={busy}
            type="checkbox"
            onChange={() => {
              setSelectedSessionIds((current) => toggleDeleteTreeSelection(
                current,
                subtreeSessionIds,
                locked ? node.sessionId : undefined,
              ));
            }}
          />
          <span>{node.title}</span>
        </label>
      </div>
      {expanded && node.children.length > 0 ? (
        <div className="project-conversation-delete-modal__tree-children">
          {node.children.map((child) => (
            <DeleteTreeItem
              key={child.sessionId}
              busy={busy}
              node={child}
              selectedSessionIds={selectedSessionIds}
              setSelectedSessionIds={setSelectedSessionIds}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function toggleDeleteTreeSelection(
  current: ReadonlySet<string>,
  subtreeSessionIds: readonly string[],
  lockedSessionId?: string,
) {
  const next = new Set(current);
  const fullySelected = subtreeSessionIds.every((subtreeSessionId) => (
    current.has(subtreeSessionId)
  ));

  subtreeSessionIds.forEach((subtreeSessionId) => {
    if (fullySelected) next.delete(subtreeSessionId);
    else next.add(subtreeSessionId);
  });
  if (lockedSessionId) next.add(lockedSessionId);
  return next;
}

function buildDeleteTree(
  response: ConversationSessionListResponse,
  targetSessionId: string,
  targetTitle: string,
): DeleteTreeNode[] {
  const sessionsById = new Map(
    response.items.map((session) => [session.session_id, session]),
  );
  const liveSessionIds = new Set(sessionsById.keys());
  const relationsBySessionId = new Map(
    response.branch_nodes.map((relation) => [relation.session_id, relation]),
  );
  const childrenByParentSessionId = new Map<string, ConversationSession[]>();

  response.items.forEach((session) => {
    if (session.session_id === targetSessionId) return;
    const relation = relationsBySessionId.get(session.session_id);
    const parentSessionId = relation
      ? nearestLiveParentSessionId(
          relation,
          relationsBySessionId,
          liveSessionIds,
        )
      : null;
    if (!parentSessionId) return;
    const siblings = childrenByParentSessionId.get(parentSessionId) ?? [];
    siblings.push(session);
    childrenByParentSessionId.set(parentSessionId, siblings);
  });

  const buildChildren = (parentSessionId: string, path: Set<string>): DeleteTreeNode[] => (
    (childrenByParentSessionId.get(parentSessionId) ?? [])
      .filter((session) => !path.has(session.session_id))
      .sort((left, right) => left.sequence_number - right.sequence_number)
      .map((session) => ({
        children: buildChildren(
          session.session_id,
          new Set([...path, session.session_id]),
        ),
        sessionId: session.session_id,
        title: session.title.trim() || "新对话",
      }))
  );

  return [{
    children: buildChildren(targetSessionId, new Set([targetSessionId])),
    sessionId: targetSessionId,
    title: targetTitle.trim() || "新对话",
  }];
}

function nearestLiveParentSessionId(
  relation: ConversationBranchNode,
  relationsBySessionId: ReadonlyMap<string, ConversationBranchNode>,
  liveSessionIds: ReadonlySet<string>,
) {
  const visited = new Set<string>();
  let parentSessionId = relation.parent_session_id;
  while (parentSessionId && !visited.has(parentSessionId)) {
    visited.add(parentSessionId);
    const parent = relationsBySessionId.get(parentSessionId);
    if (!parent) return null;
    if (parent.deleted_at === null && liveSessionIds.has(parentSessionId)) {
      return parentSessionId;
    }
    parentSessionId = parent.parent_session_id;
  }
  return null;
}

function collectTreeSessionIds(nodes: DeleteTreeNode[]): string[] {
  return nodes.flatMap((node) => [
    node.sessionId,
    ...collectTreeSessionIds(node.children),
  ]);
}
