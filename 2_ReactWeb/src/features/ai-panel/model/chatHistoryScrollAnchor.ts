/** A short-lived anchor while older history is inserted into a non-virtual list.
 * Account for scrolling during the request instead of restoring an old scrollTop.
 */
export function captureHistoryScrollAnchor(parent: HTMLElement) {
  const viewport = parent.getBoundingClientRect();
  const visible = (element: Element) => {
    const rect = element.getBoundingClientRect();
    return rect.bottom > viewport.top && rect.top < viewport.bottom;
  };
  const row = Array.from(parent.querySelectorAll<HTMLElement>("[data-chat-message-id]")).find(visible);
  if (!row) return null;
  // Prefer the body being read: expanding the preceding process is also a shift.
  const body = row.querySelector<HTMLElement>(":scope > .chat-msg__markdown");
  const element = body && visible(body) ? body : row;
  let top = element.getBoundingClientRect().top - viewport.top;
  let scrollTop = parent.scrollTop;
  return () => {
    if (!parent.contains(element)) return;
    const nextTop = element.getBoundingClientRect().top - parent.getBoundingClientRect().top;
    const shift = nextTop - top + parent.scrollTop - scrollTop;
    if (Math.abs(shift) >= 1) parent.scrollTop += shift;
    top = element.getBoundingClientRect().top - parent.getBoundingClientRect().top;
    scrollTop = parent.scrollTop;
  };
}
