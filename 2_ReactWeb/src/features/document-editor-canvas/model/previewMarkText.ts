import { anchorSelection } from "../../editor/model/documentMarks";

const blockSelector = "p,li,pre,td,th,h1,h2,h3,h4,h5,h6,blockquote,div";
const ignored = "button,script,style,[aria-hidden=true],.katex-mathml,[role=progressbar]";

// Index only rendered document text; buttons and annotation controls never enter the anchor.
export function indexPreview(root: Element) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const spans: { node: Text; start: number; end: number }[] = [];
  let text = "", previousBlock: Element | null = null;
  for (let item = walker.nextNode(); item; item = walker.nextNode()) {
    const node = item as Text;
    const parent = node.parentElement;
    if (!node.length || !parent || parent.closest(ignored)) continue;
    const block = parent.closest(blockSelector);
    if (spans.length && block !== previousBlock) text += "\n";
    previousBlock = block;
    const start = text.length;
    text += node.data;
    spans.push({ node, start, end: text.length });
  }
  return { text, spans };
}

export function previewAnchor(surface: Element, selection: Range) {
  const root = surface.querySelector(".markdown-preview--progressive");
  if (!root || !root.contains(selection.commonAncestorContainer)) return null;
  const { text, spans } = indexPreview(root);
  const selected = spans.filter(span => selection.intersectsNode(span.node));
  const first = selected[0], last = selected.at(-1);
  if (!first || !last) return null;
  const from = first.start + (first.node === selection.startContainer ? selection.startOffset : 0);
  const to = last.node === selection.endContainer ? last.start + selection.endOffset : last.end;
  return to > from ? anchorSelection(text, { from, to }, "preview") : null;
}

export function previewRange(spans: ReturnType<typeof indexPreview>["spans"], from: number, to: number) {
  const first = spans.find(s => s.start <= from && from < s.end);
  const last = spans.find(s => s.start < to && to <= s.end);
  if (!first || !last) return null;
  const range = document.createRange();
  range.setStart(first.node, from - first.start);
  range.setEnd(last.node, to - last.start);
  return range;
}
