import type { EditorImageReference } from "../../../entities/editor/model/editorReference";
import type { ExcelRange } from "./excelSelectionImage";

export function spreadsheetReferenceRange(reference: EditorImageReference): ExcelRange | null {
  const match = /^\$?([A-Z]+)\$?([1-9]\d*)(?::\$?([A-Z]+)\$?([1-9]\d*))?$/i.exec(reference.rangeAddress ?? "");
  if (!match) return null;
  const col = (text: string) => [...text.toUpperCase()].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) - 1;
  const range = { sri: Number(match[2]) - 1, sci: col(match[1]), eri: Number(match[4] ?? match[2]) - 1, eci: col(match[3] ?? match[1]) };
  if (!Object.values(range).every(n => Number.isSafeInteger(n) && n >= 0)
    || range.eri < range.sri || range.eci < range.sci) return null;
  const cells = reference.cells;
  if (!cells || cells.length !== range.eri - range.sri + 1
    || !cells.every(row => row.length === range.eci - range.sci + 1)) return null;
  return range;
}

export function spreadsheetReferenceMatches(reference: EditorImageReference, range: ExcelRange,
  value: (row: number, column: number) => unknown) {
  return reference.cells!.every((row, r) => row.every((cell, c) =>
    String(value(range.sri + r, range.sci + c) ?? "") === cell));
}
