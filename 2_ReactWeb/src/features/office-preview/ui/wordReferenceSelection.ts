import type { EditorTextReference, EditorWordTextReferencePosition } from "../../../entities/editor/model/editorReference";

function endpoint(host: HTMLElement, position: EditorWordTextReferencePosition) {
  for (const paragraph of host.querySelectorAll<HTMLElement>("p[data-word-position]")) {
    const saved = JSON.parse(paragraph.dataset.wordPosition!);
    if (saved.paragraphIndex !== position.paragraphIndex || saved.container !== position.container) continue;
    let offset = position.characterOffset - Number(paragraph.dataset.wordOffset ?? 0);
    if (offset < 0 || offset > (paragraph.textContent?.length ?? 0)) continue;
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const length = node.textContent?.length ?? 0;
      if (offset <= length) return { node, offset, paragraph };
      offset -= length;
    }
    if (offset === 0) return { node: paragraph as Node, offset: 0, paragraph };
  }
  return null;
}

export function selectWordReference(host: HTMLElement, reference: EditorTextReference) {
  const selection = host.ownerDocument.getSelection();
  selection?.removeAllRanges();
  if (!reference.location) return false;
  const start = endpoint(host, reference.location.start), end = endpoint(host, reference.location.end);
  if (!start || !end) return false;
  const range = document.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset);
  const normalized = (value: string) => value.replace(/\s+/g, "").trim();
  if (!normalized(reference.content) || normalized(range.toString()) !== normalized(reference.content)) return false;
  selection?.addRange(range);
  start.paragraph.scrollIntoView({ block: "center" });
  return Boolean(selection?.rangeCount);
}
