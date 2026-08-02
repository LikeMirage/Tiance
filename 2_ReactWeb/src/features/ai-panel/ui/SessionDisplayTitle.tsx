import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";

export function SessionDisplayTitle({ session }: { session: ConversationSession }) {
  const title = session.title.trim() || "新对话";
  if (session.sequence_number <= 0) {
    return <span className="ai-panel__session-title-label">{title}</span>;
  }

  return (
    <span className="ai-panel__session-title">
      <span className="ai-panel__session-title-index">{session.sequence_number}</span>
      <span className="ai-panel__session-title-dot">.</span>
      <span className="ai-panel__session-title-label">{title}</span>
    </span>
  );
}
