import type {
  EditorTextReference,
  EditorWordTextReferenceLocation,
  EditorWordTextReferencePosition,
} from "./editorReference";

export function textReferenceLocationLabel(reference: EditorTextReference) {
  if (reference.startLine && reference.endLine) {
    return reference.startLine === reference.endLine
      ? `L${reference.startLine}`
      : `L${reference.startLine}-L${reference.endLine}`;
  }
  if (reference.location?.kind === "word_range") {
    return wordLocationLabel(reference.location);
  }
  if (reference.source === "markdown_preview") return "Markdown 预览选区";
  if (reference.source === "markdown_visual") return "Markdown 编辑选区";
  if (reference.source === "pdf") return "PDF 选区";
  if (reference.source === "office") return "Office 文档选区";
  return "文本选区";
}

export function wordLocationLabel(location: EditorWordTextReferenceLocation) {
  const page = pageLabel(location.start.pageNumber, location.end.pageNumber);
  const start = positionLabel(location.start);
  const end = positionLabel(location.end);
  const structure = start === end ? start : `${start} 至 ${end}`;
  return [page, structure].filter(Boolean).join(" · ") || "Word 文档选区";
}

function pageLabel(start?: number, end?: number) {
  if (!start && !end) return "";
  if (!end || start === end) return `第 ${start ?? end} 页`;
  return `第 ${start ?? end}-${end} 页`;
}

function positionLabel(position: EditorWordTextReferencePosition) {
  if (
    position.container === "table" &&
    position.tableIndex &&
    position.rowIndex &&
    position.columnIndex
  ) {
    return `表格 ${position.tableIndex} 第 ${position.rowIndex} 行第 ${position.columnIndex} 列`;
  }
  if (position.paragraphIndex) return `预览段落 ${position.paragraphIndex}`;
  if (position.container === "header") return "页眉";
  if (position.container === "footer") return "页脚";
  return "";
}
