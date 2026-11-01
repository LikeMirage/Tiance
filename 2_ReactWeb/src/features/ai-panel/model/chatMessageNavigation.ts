export type ChatMessageNavigationRequest = {
  behavior?: ScrollBehavior;
  messageId: string;
  requestId: number;
  viewportOffset?: number;
};

export function findRenderedMessage(scrollElement: HTMLElement, messageId: string) {
  return Array.from(scrollElement.querySelectorAll<HTMLElement>("[data-chat-message-id]"))
    .find((element) => element.dataset.chatMessageId === messageId);
}

/** A saved reading offset needs measured content, not just a mounted row.
 * Keep correcting through virtual-row measurement until two consecutive frames
 * agree. There is no timeout that silently accepts an unfinished layout.
 */
export function startChatMessageNavigation({
  scrollElement, request, isReady, onHandled,
}: {
  scrollElement: HTMLDivElement;
  request: ChatMessageNavigationRequest;
  isReady: () => boolean;
  onHandled: (requestId: number) => void;
}) {
  let frame: number | null = null;
  let cancelled = false;
  let previousGeometry = "";
  let stableFrames = 0;
  const restore = request.viewportOffset !== undefined;
  const step = () => {
    frame = null;
    if (cancelled) return;
    const message = findRenderedMessage(scrollElement, request.messageId);
    if (!isReady() || !message || message.querySelector('[aria-busy="true"]')) {
      previousGeometry = "";
      stableFrames = 0;
      frame = window.requestAnimationFrame(step);
      return;
    }
    const top = Math.max(0, scrollElement.scrollTop + message.getBoundingClientRect().top
      - scrollElement.getBoundingClientRect().top - (request.viewportOffset ?? 8));
    scrollElement.scrollTo({ top, behavior: restore ? "auto" : request.behavior ?? "smooth" });
    if (!restore) {
      onHandled(request.requestId);
      return;
    }
    const rect = message.getBoundingClientRect();
    // Ignore changes below the anchor (e.g. a background streaming reply).
    const geometry = [scrollElement.scrollTop, rect.top, rect.height].join(":");
    stableFrames = geometry === previousGeometry ? stableFrames + 1 : 0;
    previousGeometry = geometry;
    if (stableFrames >= 2) onHandled(request.requestId);
    else frame = window.requestAnimationFrame(step);
  };
  frame = window.requestAnimationFrame(step);
  return () => {
    cancelled = true;
    if (frame !== null) window.cancelAnimationFrame(frame);
  };
}
