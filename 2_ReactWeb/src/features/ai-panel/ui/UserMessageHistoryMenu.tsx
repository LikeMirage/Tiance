import { Crosshair, ListBullets, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import type { ChatMessage } from "../model/chatMessage";
import { formatChatMessageTimestamp } from "../model/chatMessageTimestamp";
import type { useConversationNavigation } from "../model/useConversationNavigation";
import { useUserMessageDetail } from "../model/useUserMessageDetail";
import { useUserMessageSearch } from "../model/useUserMessageSearch";
import type { UserMessageNavigationItem } from "../model/userMessageNavigation";
import { buildReferencedUserMessage } from "../model/userMessageReferences";
import { ReferencedUserMessageView } from "./ReferencedUserMessageView";
import { KeywordHighlight } from "./KeywordHighlight";

export type UserMessageHistoryState = {
  projectId: string;
  sessionId: string;
  resetRevision: number | null;
  messages: ChatMessage[];
  navigation: ReturnType<typeof useConversationNavigation>;
  onLocate: (item: UserMessageNavigationItem) => void;
};

export function UserMessageHistoryMenu({ history, isOpen, onOpenChange, onOpenReference }: {
  history?: UserMessageHistoryState;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
}) {
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<CSSProperties | null>(null);
  const open = isOpen && Boolean(history);
  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const update = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(440, window.innerWidth - 16);
      const height = Math.min(260, Math.max(120, rect.top - 14), window.innerHeight - 16);
      setPosition({ width, height, left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
        top: Math.max(8, rect.top - height - 6) });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !panelRef.current?.contains(target)) onOpenChange(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onOpenChange(false);
      triggerRef.current?.focus();
    };
    window.addEventListener("mousedown", dismiss);
    window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("mousedown", dismiss); window.removeEventListener("keydown", escape); };
  }, [open, onOpenChange]);
  const close = () => { onOpenChange(false); triggerRef.current?.focus(); };
  return <>
    <button ref={triggerRef} type="button"
      className={`ai-panel__composer-add ai-panel__composer-history${open ? " ai-panel__composer-add--open" : ""}`}
      aria-label="用户消息列表" title="用户消息列表" aria-haspopup="dialog"
      aria-expanded={open} aria-controls={open ? panelId : undefined} disabled={!history}
      onClick={() => onOpenChange(!open)}>
      <ListBullets size={18} aria-hidden="true" />
    </button>
    {open && position && history && typeof document !== "undefined" ? createPortal(
      <div ref={panelRef} id={panelId} role="dialog" aria-label="用户消息列表"
        className="user-message-history" style={position}>
        <UserMessageHistoryContents key={JSON.stringify([history.projectId, history.sessionId])}
          history={history} onClose={close} onLocate={(item) => { close(); history.onLocate(item); }}
          onOpenReference={onOpenReference ? (payload) => { close(); onOpenReference(payload); } : undefined} />
      </div>, document.body,
    ) : null}
  </>;
}

function UserMessageHistoryContents({ history, onClose, onLocate, onOpenReference }: {
  history: UserMessageHistoryState;
  onClose: () => void;
  onLocate: (item: UserMessageNavigationItem) => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
}) {
  const [query, setQuery] = useState("");
  const search = useUserMessageSearch({ ...history, items: history.navigation.items, query });
  const { items, error, isLoading, retry } = query.trim() ? search : history.navigation;
  const [selection, setSelection] = useState<string | null>(null);
  const selected = items.find((item) => item.userMessageId === selection)
    ?? (query.trim() ? items[0] : items.at(-1)) ?? null;
  const selectedRef = useRef<HTMLButtonElement>(null);
  // Keep the initial selection stable when another user turn arrives.
  useEffect(() => { if (selected) setSelection(selected.userMessageId); }, [selected?.userMessageId]);
  useLayoutEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected?.userMessageId]);
  return <>
    <header className="user-message-history__head">
      <strong>用户消息</strong>
      <span className="user-message-history__count">{query.trim() ? `${items.length}/${history.navigation.items.length}` : items.length}</span>
      <label className="user-message-history__search">
        <MagnifyingGlass size={14} aria-hidden="true" />
        <input type="search" aria-label="搜索用户消息" placeholder="搜索关键词" value={query}
          onChange={event => setQuery(event.target.value)} />
      </label>
      <button className="ai-panel__composer-add" type="button" aria-label="关闭用户消息列表" onClick={onClose}>
        <X size={15} aria-hidden="true" />
      </button>
    </header>
    {error ? <div className="user-message-history__error" role="alert">
      <span>{error}</span><button type="button" onClick={retry}>重试</button>
    </div> : null}
    <div className="user-message-history__body">
      <nav className="user-message-history__list" aria-label="历史用户消息">
        {items.map((item) => <div className="user-message-history__row" key={item.userMessageId}
          data-selected={item.userMessageId === selected?.userMessageId || undefined}>
          <button type="button" className="user-message-history__select"
            ref={item.userMessageId === selected?.userMessageId ? selectedRef : undefined}
            aria-pressed={item.userMessageId === selected?.userMessageId}
            onClick={() => setSelection(item.userMessageId)} title={item.userPreview}>
            <span className="user-message-history__number">{item.turnNumber}</span>
            <span className="user-message-history__preview"><KeywordHighlight text={item.userPreview} keyword={query} /></span>
          </button>
          <button type="button" className="ai-panel__composer-add user-message-history__locate"
            aria-label={`定位第 ${item.turnNumber} 条用户消息`} title="定位到消息"
            onClick={() => onLocate(item)}><Crosshair size={15} aria-hidden="true" /></button>
        </div>)}
        {!items.length && !error ? <p className="user-message-history__empty" role="status">
          {isLoading ? (query.trim() ? "正在搜索…" : "正在加载消息列表…") : query.trim() ? "没有匹配的消息" : "暂无用户消息"}
        </p> : null}
      </nav>
      <UserMessageHistoryDetail key={selected?.userMessageId ?? "empty"} history={history}
        selected={selected} keyword={query} onOpenReference={onOpenReference} />
    </div>
  </>;
}

function UserMessageHistoryDetail({ history, selected, keyword, onOpenReference }: {
  history: UserMessageHistoryState;
  selected: UserMessageNavigationItem | null;
  keyword: string;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
}) {
  const { message, error, retry } = useUserMessageDetail({ ...history, messageId: selected?.userMessageId ?? null });
  const referenced = message ? buildReferencedUserMessage(message) : null;
  const timestamp = formatChatMessageTimestamp(message?.createdAt);
  return <section className="user-message-history__detail" aria-label="用户消息详情">
    {!selected ? null : error ? <div className="user-message-history__error" role="alert">
      <span>{error}</span><button type="button" onClick={retry}>重试</button>
    </div> : !message ? <p className="user-message-history__empty" role="status">正在加载消息…</p> : <>
      <div className="user-message-history__meta"><span>{selected.turnNumber}</span>
        {timestamp ? <time dateTime={timestamp.dateTime}>{timestamp.label}</time> : null}
      </div>
      {referenced ? <ReferencedUserMessageView {...referenced} highlight={keyword}
        onOpenReference={onOpenReference ? (reference) => onOpenReference(reference.viewerPayload) : undefined} />
        : <p className="chat-msg__text"><KeywordHighlight text={message.content} keyword={keyword} /></p>}
    </>}
  </section>;
}
