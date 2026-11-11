import { File, Folder, ImageSquare, Quotes } from "@phosphor-icons/react";
import type { UserMessageReferenceDisplay } from "../model/userMessageReferences";
import { KeywordHighlight } from "./KeywordHighlight";

export function ReferencedUserMessageView({
  onOpenReference,
  references,
  userContent,
  highlight,
}: {
  onOpenReference?: (reference: UserMessageReferenceDisplay) => void;
  references: UserMessageReferenceDisplay[];
  userContent: string;
  highlight?: string;
}) {
  return (
    <>
      <section className="chat-msg__user-reference-panel" aria-label="用户引用内容">
        <div className="chat-msg__user-reference-head">引用 {references.length}</div>
        <div className="chat-msg__user-reference-list">
          {references.map((reference) => (
            <div className="chat-msg__user-reference" key={`${reference.index}-${reference.title}-${reference.meta}`}>
              <button
                className={onOpenReference
                  ? "chat-msg__user-reference-open"
                  : "chat-msg__user-reference-open chat-msg__user-reference-open--static"}
                disabled={!onOpenReference}
                title={onOpenReference ? "查看引用内容" : undefined}
                type="button"
                onClick={() => onOpenReference?.(reference)}
              >
                <span className="chat-msg__user-reference-index">No. {reference.index}</span>
                <span className="chat-msg__user-reference-icon" aria-hidden="true">
                  <UserReferenceIcon reference={reference} />
                </span>
                <div className="chat-msg__user-reference-body">
                  <div className="chat-msg__user-reference-main">
                    <strong title={reference.title}><KeywordHighlight text={reference.title} keyword={highlight} /></strong>
                    <span><KeywordHighlight text={reference.meta} keyword={highlight} /></span>
                  </div>
                  {reference.detail ? (
                    <div className="chat-msg__user-reference-detail" title={reference.detail}>
                      <KeywordHighlight text={reference.detail} keyword={highlight} />
                    </div>
                  ) : null}
                </div>
              </button>
            </div>
          ))}
        </div>
      </section>
      {userContent.trim() ? (
        <p className="chat-msg__text chat-msg__user-reference-message"><KeywordHighlight text={userContent} keyword={highlight} /></p>
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
