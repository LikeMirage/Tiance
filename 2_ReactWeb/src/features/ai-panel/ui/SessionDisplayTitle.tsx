import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";

export function SessionDisplayTitle({ session, displaySequence }: {
  session: ConversationSession;
  displaySequence: number | null;
}) {
  const title = session.title.trim() || "新对话";
  if (displaySequence === null) {
    return <span className="ai-panel__session-title-label">{title}</span>;
  }

  return (
    <span className="ai-panel__session-title">
      <span className="ai-panel__session-title-index">{displaySequence}</span>
      <span className="ai-panel__session-title-dot">.</span>
      <span className="ai-panel__session-title-label">{title}</span>
    </span>
  );
}
