export type ChatScrollPosition = {
  anchorMessageId: string | null;
  anchorViewportOffset: number;
  isFollowingBottom: boolean;
  scrollTop: number;
};

export type ChatScrollRestoreRequest = {
  behavior: "auto";
  messageId: string;
  requestId: number;
  sessionKey: string;
  viewportOffset: number;
};

export function captureChatScrollPosition(
  scrollElement: HTMLDivElement,
  nearBottomPx: number,
): ChatScrollPosition {
  const viewport = scrollElement.getBoundingClientRect();
  const anchor = Array.from(
    scrollElement.querySelectorAll<HTMLElement>("[data-chat-message-id]"),
  ).find((element) => element.getBoundingClientRect().bottom > viewport.top);
  const distanceToBottom =
    scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight;

  return {
    anchorMessageId: anchor?.dataset.chatMessageId ?? null,
    anchorViewportOffset: anchor
      ? anchor.getBoundingClientRect().top - viewport.top
      : 0,
    isFollowingBottom: distanceToBottom < nearBottomPx,
    scrollTop: scrollElement.scrollTop,
  };
}
