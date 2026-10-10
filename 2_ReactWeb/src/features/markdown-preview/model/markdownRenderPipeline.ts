import { defaultUrlTransform } from "react-markdown";
import { urlAttributes } from "html-url-attributes";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { fromHtmlIsomorphic } from "hast-util-from-html-isomorphic";
import { toHtml } from "hast-util-to-html";
import { markdownHtmlSanitizeSchema } from "./markdownHtmlSanitizeSchema";
import { normalizeMarkdownMath, markdownMathRemarkPlugins, markdownMathRehypePlugins,
  findMarkdownMathRanges, shouldRenderTableMathAsDisplay } from "./markdownMath";
import { renderMarkdownKatex } from "./markdownKatex";
import { remarkLocalFilePaths } from "./remarkLocalFilePaths";
import type { MarkdownRenderDocument, MarkdownRenderElement, MarkdownRenderRoot } from "./markdownRenderDocument";
import { MARKDOWN_BLOCK_PREFIX } from "./markdownRenderDocument";

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkLocalFilePaths)
  .use(markdownMathRemarkPlugins)
  .use(remarkRehype, { allowDangerousHtml: true })
  .use(rehypeRaw)
  .use(rehypeSanitize, markdownHtmlSanitizeSchema)
  .use(markdownMathRehypePlugins);

export function parseMarkdownRenderTree(content: string) {
  const fences = content.match(/```/g);
  const source = normalizeMarkdownMath(fences && fences.length % 2 ? `${content}\n\`\`\`` : content);
  const tree = processor.runSync(processor.parse(source)) as MarkdownRenderRoot;
  renderTableMath(tree);
  const transform = (node: MarkdownRenderRoot | MarkdownRenderRoot["children"][number]) => {
    if (node.type === "element") {
      for (const [key, tags] of Object.entries(urlAttributes)) {
        if (Object.hasOwn(node.properties, key) && (tags === null || tags.includes(node.tagName))) {
          const value = String(node.properties[key] || "");
          node.properties[key] = value.startsWith("tiance-local-path:") ? value : defaultUrlTransform(value);
        }
      }
    }
    if ("children" in node) node.children.forEach(transform);
  };
  transform(tree);
  return tree;
}

export function prepareMarkdownRender(content: string): MarkdownRenderDocument {
  const tree = parseMarkdownRenderTree(content);
  const slots: MarkdownRenderElement[] = [];
  let slotWeight = 0;
  const serialize = (node: MarkdownRenderRoot | MarkdownRenderRoot["children"][number]): typeof node => {
    if (node.type === "element" && ["pre", "a", "img"].includes(node.tagName)) {
      const id = slots.length;
      slots.push(node);
      slotWeight += toHtml(node).length;
      return { type: "element", tagName: node.tagName === "pre" ? "div" : "span",
        properties: { dataMarkdownSlot: id }, children: [] };
    }
    if (!("children" in node)) return node;
    const children = node.children.map(serialize).filter((child) => child.type !== "root" && child.type !== "doctype");
    const next = { ...node, children };
    if (node.type === "element" && node.tagName === "table") {
      return { type: "element", tagName: "div", properties: { className: ["markdown-preview__table-wrap"] },
        children: [next as MarkdownRenderElement] };
    }
    return next;
  };
  const blocks: string[] = [];
  type Child = MarkdownRenderRoot["children"][number];
  const fragment = (children: Child[]): Child => {
    const id = blocks.length;
    blocks.push(toHtml({ type: "root", children }));
    return { type: "comment", value: `${MARKDOWN_BLOCK_PREFIX}${id}` };
  };
  const group = (items: { node: Child; size: number }[]) => {
    const children: Child[] = [];
    let pending: Child[] = [];
    let size = 0;
    for (const item of items) {
      if (pending.length && size + item.size > 800) { children.push(fragment(pending)); pending = []; size = 0; }
      pending.push(item.node);
      size += item.size;
    }
    if (pending.length) children.push(fragment(pending));
    return children;
  };
  const pack = <T extends Child>(node: T): { node: T; size: number } => {
    if (node.type !== "element") return { node, size: 1 };
    const items = node.children.map(pack);
    const size = 1 + items.reduce((sum, item) => sum + item.size, 0);
    const children = size > 800 ? group(items) : items.map((item) => item.node);
    return { node: { ...node, children } as T, size: size > 800 ? 1 + children.length : size };
  };
  const serialized = serialize(tree) as MarkdownRenderRoot;
  const html = toHtml({ ...serialized, children: group(serialized.children.map(pack)) });
  return { html, blocks, slots, cacheWeight: content.length + html.length + slotWeight + blocks.reduce((sum, block) => sum + block.length, 0) };
}

// Match the complete renderer's table-cell fallback before cells become fragments.
// Embedded display delimiters can remain text after remark-math, even in a large table.
function renderTableMath(node: MarkdownRenderRoot | MarkdownRenderRoot["children"][number]) {
  if (!("children" in node)) return;
  if (node.type === "element" && (node.tagName === "td" || node.tagName === "th")) {
    node.children = node.children.flatMap((child) => {
      if (child.type !== "text") return [child];
      const text = child.value;
      const ranges = findMarkdownMathRanges(text).filter((range) => range.closed);
      const children: typeof node.children = [];
      let cursor = 0;
      for (const range of ranges) {
        if (range.start > cursor) children.push({ type: "text", value: text.slice(cursor, range.start) });
        const latex = text.slice(range.bodyStart, range.bodyEnd).trim();
        if (latex) {
          const displayMode = shouldRenderTableMathAsDisplay(range.displayMode, latex);
          const rendered = renderMarkdownKatex(latex, displayMode);
          children.push({ type: "element", tagName: "span", properties: {
            className: ["markdown-preview__table-cell-math",
              ...(displayMode ? ["markdown-preview__table-cell-math--display"] : []),
              ...(rendered.error ? ["markdown-preview__math-error"] : [])],
            ...(rendered.error ? { dataMathRenderError: "true", title: rendered.error } : {}),
          }, children: fromHtmlIsomorphic(rendered.html, { fragment: true }).children.filter((child) => child.type !== "doctype") });
        } else children.push({ type: "text", value: text.slice(range.start, range.end) });
        cursor = range.end;
      }
      if (cursor < text.length) children.push({ type: "text", value: text.slice(cursor) });
      return children;
    });
    return;
  }
  node.children.forEach(renderTableMath);
}
