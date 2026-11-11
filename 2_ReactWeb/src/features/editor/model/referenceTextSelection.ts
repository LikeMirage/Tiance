import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { resolveReferenceText } from "../../../entities/editor/model/documentReveal";
import type { EditorTextReference } from "../../../entities/editor/model/editorReference";

type Doc = Parameters<typeof resolveReferenceText>[0];
type Node = { type: string; value?: string; children?: Node[]; position?: { start: { offset?: number }; end: { offset?: number } } };

/** Rendered Markdown omits delimiters. Map a unique quote back to source offsets,
 * never using stored line numbers alone after the file changed. */
export function findReferenceTextSelection(doc: Doc, reference: EditorTextReference, markdown: boolean) {
  try { return resolveReferenceText(doc, reference); } catch { /* Try rendered Markdown below. */ }
  if (!markdown || !["markdown_preview", "markdown_visual"].includes(reference.source)) return null;
  const content = doc.toString();
  const chars: { value: string; from: number; to: number }[] = [];
  const append = (value: string, from: number, to: number) => {
    if (/\s/.test(value)) {
      if (chars.at(-1)?.value !== " ") chars.push({ value: " ", from, to });
    } else chars.push({ value, from, to });
  };
  const visit = (node: Node) => {
    const start = node.position?.start.offset;
    const end = node.position?.end.offset;
    if (start === undefined || end === undefined) return;
    if (node.value !== undefined && ["text", "inlineCode", "code"].includes(node.type)) {
      const offset = content.slice(start, end).indexOf(node.value);
      // Escapes/entities without a direct mapping are deliberately not guessed.
      if (offset < 0) { append("\u0000", start, end); return; }
      for (let i = 0; i < node.value.length; i++) append(node.value[i], start + offset + i, start + offset + i + 1);
    } else {
      node.children?.forEach(visit);
      if (["paragraph", "heading", "listItem", "tableCell", "tableRow", "break", "code"].includes(node.type)) append(" ", end, end);
    }
  };
  visit(unified().use(remarkParse).use(remarkGfm).parse(content) as Node);
  const text = chars.map(char => char.value).join("");
  const needle = reference.content.replace(/\s+/g, " ").trim();
  const index = needle ? text.indexOf(needle) : -1;
  if (index < 0 || text.indexOf(needle, index + 1) >= 0) return null;
  const from = chars[index].from;
  const to = chars[index + needle.length - 1].to;
  const start = doc.lineAt(from), end = doc.lineAt(to);
  return { type: "text_selection" as const, from, to, start_line: start.number, end_line: end.number,
    start_column: from - start.from + 1, end_column: to - end.from + 1, source: "editor_buffer" as const };
}
