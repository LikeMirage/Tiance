import type {
  EditorWordTextReferenceLocation,
  EditorWordTextReferencePosition,
} from "../../../entities/editor/model/editorReference";

const CONTEXT_LENGTH = 80;

export function readWordTextReferenceLocation(
  surface: HTMLElement,
  range: Range,
): EditorWordTextReferenceLocation {
  const start = locatePosition(surface, range.startContainer, range.startOffset);
  const end = locatePosition(surface, range.endContainer, range.endOffset);
  const startParagraph = closestElement(range.startContainer, "p");
  const endParagraph = closestElement(range.endContainer, "p");
  const startOffset = textOffset(startParagraph, range.startContainer, range.startOffset);
  const endOffset = textOffset(endParagraph, range.endContainer, range.endOffset);
  return compactLocation({
    kind: "word_range",
    start: { ...start, characterOffset: startOffset },
    end: { ...end, characterOffset: endOffset },
    nearestHeading: nearestHeading(surface, startParagraph),
    prefix: contextBefore(startParagraph, startOffset),
    suffix: contextAfter(endParagraph, endOffset),
  });
}

function locatePosition(
  surface: HTMLElement,
  node: Node,
  offset: number,
): EditorWordTextReferencePosition {
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
  const page = element?.closest("section.office-docx");
  const paragraph = element?.closest("p");
  const cell = element?.closest("td, th") as HTMLTableCellElement | null;
  const table = cell?.closest("table") ?? element?.closest("table");
  const row = cell?.closest("tr") as HTMLTableRowElement | null;
  const container = cell
    ? "table"
    : element?.closest("header")
      ? "header"
      : element?.closest("footer")
        ? "footer"
        : element?.closest("article")
          ? "body"
          : "unknown";
  return compactPosition({
    container,
    characterOffset: offset,
    pageNumber: ordinal(surface.querySelectorAll("section.office-docx"), page),
    paragraphIndex: ordinal(wordParagraphs(surface), paragraph),
    tableIndex: ordinal(wordTables(surface), table),
    rowIndex: row && table ? ordinalTableRow(table, row) : undefined,
    columnIndex: cell && row && table ? tableGridColumnIndex(table, row, cell) : undefined,
    cellParagraphIndex: cell && paragraph ? ordinal(cell.querySelectorAll("p"), paragraph) : undefined,
  });
}

function wordParagraphs(surface: HTMLElement) {
  return surface.querySelectorAll("section.office-docx > article p");
}

function wordTables(surface: HTMLElement) {
  return surface.querySelectorAll("section.office-docx > article table");
}

function ordinal(nodes: NodeListOf<Element>, target: Element | null | undefined) {
  if (!target) return undefined;
  const index = Array.from(nodes).indexOf(target);
  return index >= 0 ? index + 1 : undefined;
}

function ordinalTableRow(table: HTMLTableElement, target: HTMLTableRowElement) {
  const index = Array.from(table.rows).indexOf(target);
  return index >= 0 ? index + 1 : undefined;
}

function tableGridColumnIndex(
  table: HTMLTableElement,
  targetRow: HTMLTableRowElement,
  targetCell: HTMLTableCellElement,
) {
  const occupied = new Map<number, Set<number>>();
  for (const [rowIndex, row] of Array.from(table.rows).entries()) {
    let column = 1;
    for (const cell of Array.from(row.cells)) {
      while (occupied.get(rowIndex)?.has(column)) column += 1;
      if (row === targetRow && cell === targetCell) return column;
      const columnSpan = Math.max(1, cell.colSpan || 1);
      const rowSpan = Math.max(1, cell.rowSpan || 1);
      for (let rowOffset = 1; rowOffset < rowSpan; rowOffset += 1) {
        const futureRow = rowIndex + rowOffset;
        const rowOccupancy = occupied.get(futureRow) ?? new Set<number>();
        for (let columnOffset = 0; columnOffset < columnSpan; columnOffset += 1) {
          rowOccupancy.add(column + columnOffset);
        }
        occupied.set(futureRow, rowOccupancy);
      }
      column += columnSpan;
    }
  }
  return undefined;
}

function closestElement(node: Node, selector: string) {
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
  return element?.closest(selector) as HTMLElement | null;
}

function textOffset(paragraph: HTMLElement | null, node: Node, offset: number) {
  if (!paragraph || !paragraph.contains(node)) return 0;
  const prefix = document.createRange();
  prefix.selectNodeContents(paragraph);
  try {
    prefix.setEnd(node, offset);
  } catch {
    return 0;
  }
  return prefix.toString().length;
}

function nearestHeading(surface: HTMLElement, paragraph: HTMLElement | null) {
  if (!paragraph) return undefined;
  const paragraphs = Array.from(wordParagraphs(surface));
  const position = paragraphs.indexOf(paragraph);
  for (let index = position; index >= 0; index -= 1) {
    const candidate = paragraphs[index];
    if (!isHeading(candidate)) continue;
    const value = normalizeText(candidate.textContent);
    if (value) return value;
  }
  return undefined;
}

function isHeading(element: Element) {
  return /^H[1-6]$/.test(element.tagName) || /(^|[_-])(heading|title)([_-]|$)/i.test(element.className);
}

function contextBefore(paragraph: HTMLElement | null, offset: number) {
  const value = paragraph?.textContent ?? "";
  return normalizeText(value.slice(Math.max(0, offset - CONTEXT_LENGTH), offset)) || undefined;
}

function contextAfter(paragraph: HTMLElement | null, offset: number) {
  const value = paragraph?.textContent ?? "";
  return normalizeText(value.slice(offset, offset + CONTEXT_LENGTH)) || undefined;
}

function normalizeText(value: string | null) {
  return value?.replace(/\s+/g, " ").trim() ?? "";
}

function compactLocation(location: EditorWordTextReferenceLocation) {
  return Object.fromEntries(
    Object.entries(location).filter(([, value]) => value !== undefined && value !== ""),
  ) as EditorWordTextReferenceLocation;
}

function compactPosition(position: EditorWordTextReferencePosition) {
  return Object.fromEntries(
    Object.entries(position).filter(([, value]) => value !== undefined),
  ) as EditorWordTextReferencePosition;
}
