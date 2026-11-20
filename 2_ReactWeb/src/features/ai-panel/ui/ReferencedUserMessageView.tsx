import { File, Folder, ImageSquare, Quotes } from "@phosphor-icons/react";
import { useState } from "react";
import type { UserMessageReferenceDisplay } from "../model/userMessageReferences";
import { KeywordHighlight } from "./KeywordHighlight";
import { UserMessageText } from "./UserMessageText";

export function ReferencedUserMessageView({
  onOpenReference,
  references,
  userContent,
  highlight,
  compact = false,
}: {
  onOpenReference?: (reference: UserMessageReferenceDisplay) => void;
  references: UserMessageReferenceDisplay[];
  userContent: string;
  highlight?: string;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleReferences = compact && !expanded ? references.slice(0, 2) : references;
  return (
    <>
      <section className={`chat-msg__user-reference-panel${compact ? " chat-msg__user-reference-panel--compact" : ""}`} aria-label="用户引用内容">
        <div className="chat-msg__user-reference-head">引用 {references.length}</div>
        <div className="chat-msg__user-reference-list">
          {visibleReferences.map((reference) => (
            <div className="chat-msg__user-reference" key={`${reference.index}-${reference.title}-${reference.meta}`}>
              <button
                className={onOpenReference
                  ? "chat-msg__user-reference-open"
                  : "chat-msg__user-reference-open chat-msg__user-reference-open--static"}
                disabled={!onOpenReference}
                title={compact ? [reference.title, reference.meta, reference.detail].filter(Boolean).join("\n")
                  : onOpenReference ? "查看引用内容" : undefined}
                aria-label={compact ? `查看引用：${reference.title}` : undefined}
                type="button"
                onClick={() => onOpenReference?.(reference)}
              >
                <span className="chat-msg__user-reference-index">No. {reference.index}</span>
                <span className="chat-msg__user-reference-icon" aria-hidden="true">
                  <UserReferenceIcon reference={reference} />
                </span>
                <div className="chat-msg__user-reference-body">
                  <div className="chat-msg__user-reference-main">
                    <strong title={compact ? undefined : reference.title}><KeywordHighlight text={reference.title} keyword={highlight} /></strong>
                    {!compact ? <span><KeywordHighlight text={reference.meta} keyword={highlight} /></span> : null}
                  </div>
                  {!compact && reference.detail ? (
                    <div className="chat-msg__user-reference-detail" title={reference.detail}>
                      <KeywordHighlight text={reference.detail} keyword={highlight} />
                    </div>
                  ) : null}
                </div>
              </button>
            </div>
          ))}
        </div>
        {compact && references.length > 2 ? <button type="button"
          className="chat-msg__user-reference-expand" aria-expanded={expanded}
          onClick={() => setExpanded(value => !value)}>
          {expanded ? "收起引用" : `展开其余 ${references.length - 2} 条`}
        </button> : null}
      </section>
      {userContent.trim() ? (
        <p className="chat-msg__text chat-msg__user-reference-message"><UserMessageText text={userContent} keyword={highlight} /></p>
      ) : null}
    </>
  );
}

function UserReferenceIcon({ reference }: { reference: UserMessageReferenceDisplay }) {
  if (reference.kind === "folder") return <Folder size={15} weight="bold" />;
  if (reference.kind === "text") return <Quotes size={15} weight="bold" />;
  if (reference.kind === "image" || reference.kind === "pdf" || reference.kind === "ppt" || reference.kind === "excel") {
    return <ImageSquare size={15} weight="bold" />;
  }
  return <File size={15} weight="bold" />;
}
