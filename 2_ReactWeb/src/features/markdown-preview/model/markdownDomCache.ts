import type { MarkdownRenderDocument } from "./markdownRenderDocument";

// Cache small, inert blocks before their nested anchors and React controls mount.
// Reusing a whole document in one clone would block the loading animation.
const templates = new Map<MarkdownRenderDocument, { blocks: Map<number, DocumentFragment>; nodes: number }>();
let totalNodes = 0;
let totalChars = 0;

export function getMarkdownDomBlock(document: MarkdownRenderDocument, id: number) {
  const template = templates.get(document);
  if (!template) return undefined;
  templates.delete(document);
  templates.set(document, template);
  return template.blocks.get(id);
}

export function rememberMarkdownDomBlock(document: MarkdownRenderDocument, id: number, fragment: DocumentFragment) {
  if (document.cacheWeight > 8_000_000) return;
  let template = templates.get(document);
  if (template?.blocks.has(id)) return;
  const nodes = fragment.querySelectorAll("*").length;
  if (!template) {
    template = { blocks: new Map(), nodes: 0 };
    templates.set(document, template);
    totalChars += document.cacheWeight;
  }
  template.blocks.set(id, fragment.cloneNode(true) as DocumentFragment);
  template.nodes += nodes;
  totalNodes += nodes;
  while (totalNodes > 100_000 || totalChars > 8_000_000 || templates.size > 16) {
    const [oldDocument, oldTemplate] = templates.entries().next().value!;
    templates.delete(oldDocument);
    totalNodes -= oldTemplate.nodes;
    totalChars -= oldDocument.cacheWeight;
  }
}
