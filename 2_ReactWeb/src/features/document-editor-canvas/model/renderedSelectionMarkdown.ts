export function renderedSelectionMarkdown(range: Range) {
  const container = document.createElement("div");
  container.append(range.cloneContents());
  const markdown = Array.from(container.childNodes)
    .map((node) => blockMarkdown(node))
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return markdown || range.toString().trim();
}

function blockMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return normalizeInline(node.textContent ?? "");
  if (!(node instanceof HTMLElement)) return "";
  const tag = node.tagName.toLowerCase();
  if (/^h[1-6]$/.test(tag)) {
    return `${"#".repeat(Number(tag[1]))} ${inlineChildren(node)}\n\n`;
  }
  if (tag === "table") return `${tableMarkdown(node as HTMLTableElement)}\n\n`;
  if (tag === "ul" || tag === "ol") return `${listMarkdown(node, tag === "ol")}\n`;
  if (tag === "p") return `${inlineChildren(node)}\n\n`;
  if (tag === "br") return "\n";
  return Array.from(node.childNodes).map((child) => blockMarkdown(child)).join("");
}

function inlineMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return normalizeInline(node.textContent ?? "");
  if (!(node instanceof HTMLElement)) return "";
  const tag = node.tagName.toLowerCase();
  const content = inlineChildren(node);
  if (!content) return "";
  if (tag === "br") return "\n";
  if (tag === "strong" || tag === "b") return `**${content}**`;
  if (tag === "em" || tag === "i") return `*${content}*`;
  if (tag === "code") return `\`${content.replace(/`/g, "\\`")}\``;
  if (tag === "a") {
    const href = node.getAttribute("href");
    return href ? `[${content}](${href})` : content;
  }
  return content;
}

function inlineChildren(element: Element) {
  return Array.from(element.childNodes).map((child) => inlineMarkdown(child)).join("").trim();
}

function listMarkdown(list: HTMLElement, ordered: boolean) {
  return Array.from(list.children)
    .filter((child) => child.tagName.toLowerCase() === "li")
    .map((item, index) => `${ordered ? `${index + 1}.` : "-"} ${inlineChildren(item)}`)
    .join("\n");
}

function tableMarkdown(table: HTMLTableElement) {
  const grid: string[][] = [];
  Array.from(table.rows).forEach((row, rowIndex) => {
    grid[rowIndex] ??= [];
    let columnIndex = 0;
    Array.from(row.cells).forEach((cell) => {
      while (grid[rowIndex][columnIndex] !== undefined) columnIndex += 1;
      const rowSpan = Math.max(1, cell.rowSpan || 1);
      const columnSpan = Math.max(1, cell.colSpan || 1);
      for (let rowOffset = 0; rowOffset < rowSpan; rowOffset += 1) {
        grid[rowIndex + rowOffset] ??= [];
        for (let columnOffset = 0; columnOffset < columnSpan; columnOffset += 1) {
          grid[rowIndex + rowOffset][columnIndex + columnOffset] =
            rowOffset === 0 && columnOffset === 0 ? inlineChildren(cell) : "";
        }
      }
      columnIndex += columnSpan;
    });
  });
  const width = Math.max(0, ...grid.map((row) => row.length));
  if (!width) return "";
  const rows = grid.map((row) => Array.from({ length: width }, (_, index) => escapeCell(row[index] ?? "")));
  const separator = Array.from({ length: width }, () => "---");
  return [rows[0], separator, ...rows.slice(1)]
    .map((row) => `| ${row.join(" | ")} |`)
    .join("\n");
}

function escapeCell(value: string) {
  return value.replace(/\|/g, "\\|").replace(/\s*\n\s*/g, "<br>").trim();
}

function normalizeInline(value: string) {
  return value.replace(/\s+/g, " ");
}
