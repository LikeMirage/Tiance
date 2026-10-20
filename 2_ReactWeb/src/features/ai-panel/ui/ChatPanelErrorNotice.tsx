import { X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

type Props = {
  message: string | null;
  scopeKey: string | null;
  onRetry?: () => void;
};

export function ChatPanelErrorNotice({ message, ...props }: Props) {
  // A cleared or changed error starts a new notice, even if the same text recurs.
  return message ? <ErrorNotice key={message} message={message} {...props} /> : null;
}

function ErrorNotice({ message, scopeKey, onRetry }: Props) {
  const [initialScopeKey] = useState(scopeKey);
  const [visible, setVisible] = useState(true);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const isCurrentScope = initialScopeKey === scopeKey;

  useEffect(() => {
    // Keep it dismissed when the user returns to the original conversation.
    if (!isCurrentScope) setVisible(false);
  }, [isCurrentScope]);

  useEffect(() => {
    if (!visible || !isCurrentScope || hovered || focused) return;
    const timer = window.setTimeout(() => setVisible(false), 8_000);
    return () => window.clearTimeout(timer);
  }, [focused, hovered, isCurrentScope, visible]);

  if (!visible || !isCurrentScope) return null;

  return (
    <div
      className="ai-panel__inline-error"
      role="status"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
    >
      <span className="ai-panel__inline-error-message">{message}</span>
      {onRetry ? <button type="button" onClick={onRetry}>重试</button> : null}
      <button
        aria-label="关闭提示"
        className="ai-panel__inline-error-dismiss"
        title="关闭提示"
        type="button"
        onClick={() => setVisible(false)}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
