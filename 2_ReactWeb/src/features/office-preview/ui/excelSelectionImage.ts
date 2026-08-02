import type { JsExcelPreview } from "@js-preview/excel";

type ExcelRange = {
  eci: number;
  eri: number;
  sci: number;
  sri: number;
};

type ExcelCell = {
  merge?: [number, number];
  style?: number;
  text?: unknown;
};

type ExcelStyle = {
  align?: "left" | "center" | "right";
  bgcolor?: string;
  border?: Partial<Record<"bottom" | "left" | "right" | "top", [string, string]>>;
  color?: string;
  font?: {
    bold?: boolean;
    italic?: boolean;
    name?: string;
    size?: number;
  };
  textwrap?: boolean;
  valign?: "bottom" | "middle" | "top";
};

type RuntimeSheetData = {
  cols?: {
    getWidth?: (colIndex: number) => number;
  };
  getCell?: (rowIndex: number, colIndex: number) => ExcelCell | null;
  getCellStyleOrDefault?: (rowIndex: number, colIndex: number) => ExcelStyle;
  name?: unknown;
  rows?: {
    getHeight?: (rowIndex: number) => number;
  };
  selector?: {
    range?: ExcelRange;
  };
};

type RuntimeSpreadsheet = {
  sheet?: {
    data?: RuntimeSheetData;
  };
};

type InternalExcelPreviewer = JsExcelPreview & {
  sheetIndex?: number;
  xs?: RuntimeSpreadsheet;
};

export type ExcelSelectionImageReferencePayload = {
  cells: string[][];
  file: File;
  rangeAddress: string;
  sheetName: string;
  sourceDisplayPath: string;
  sourceFileName: string;
};

const defaultColumnWidth = 80;
const defaultRowHeight = 24;
const maxCanvasSide = 8192;
const maxCanvasArea = 16_000_000;
const outputPixelRatio = 2;

export async function copyExcelSelectionAsImage(previewer: JsExcelPreview | null) {
  const { canvas } = renderExcelSelection(previewer);
  try {
    await writeCanvasPngToClipboard(canvas);
  } finally {
    releaseCanvas(canvas);
  }
}

export async function renderExcelSelectionToPngFile(
  previewer: JsExcelPreview | null,
  sourceFileName: string,
) {
  const { canvas, range, sheet, sheetName } = renderExcelSelection(previewer);
  try {
    const blob = await canvasToPngBlob(canvas);
    return {
      cells: collectExcelSelectionCells(sheet, range),
      file: new File(
        [blob],
        buildExcelSelectionImageFileName(sourceFileName, sheetName, formatExcelRangeAddress(range)),
        { type: "image/png" },
      ),
      rangeAddress: formatExcelRangeAddress(range),
      sheetName,
    };
  } finally {
    releaseCanvas(canvas);
  }
}

function renderExcelSelection(previewer: JsExcelPreview | null) {
  const internalPreviewer = previewer as InternalExcelPreviewer | null;
  const sheet = resolveActiveSheet(internalPreviewer);
  const range = normalizeRange(sheet.selector?.range);
  if (!range) {
    throw new Error("当前没有可复制的 Excel 选区。");
  }

  return {
    canvas: renderExcelSelectionToCanvas(sheet, range),
    range,
    sheet,
    sheetName: resolveActiveSheetName(internalPreviewer, sheet),
  };
}

function resolveActiveSheet(previewer: InternalExcelPreviewer | null): RuntimeSheetData {
  const sheet = previewer?.xs?.sheet?.data;
  if (!sheet) {
    throw new Error("Excel 预览尚未准备好。");
  }

  return sheet;
}

function resolveActiveSheetName(previewer: InternalExcelPreviewer | null, sheet: RuntimeSheetData) {
  if (typeof sheet.name === "string" && sheet.name.trim()) {
    return sheet.name.trim();
  }
  const index = typeof previewer?.sheetIndex === "number" ? previewer.sheetIndex : 0;
  return `Sheet${index + 1}`;
}

function normalizeRange(range: ExcelRange | undefined): ExcelRange | null {
  if (!range) return null;

  const sri = Math.min(range.sri, range.eri);
  const eri = Math.max(range.sri, range.eri);
  const sci = Math.min(range.sci, range.eci);
  const eci = Math.max(range.sci, range.eci);
  if (sri < 0 || sci < 0 || eri < sri || eci < sci) return null;
  if (![sri, eri, sci, eci].every(Number.isFinite)) return null;

  return { eci, eri, sci, sri };
}

function renderExcelSelectionToCanvas(sheet: RuntimeSheetData, range: ExcelRange) {
  const rowHeights = collectSizes(range.sri, range.eri, (index) => sheet.rows?.getHeight?.(index) ?? defaultRowHeight);
  const columnWidths = collectSizes(range.sci, range.eci, (index) => sheet.cols?.getWidth?.(index) ?? defaultColumnWidth);
  const width = Math.max(1, Math.ceil(sum(columnWidths)));
  const height = Math.max(1, Math.ceil(sum(rowHeights)));
  const scaledWidth = Math.ceil(width * outputPixelRatio);
  const scaledHeight = Math.ceil(height * outputPixelRatio);

  if (scaledWidth > maxCanvasSide || scaledHeight > maxCanvasSide || scaledWidth * scaledHeight > maxCanvasArea) {
    throw new Error("选区过大，无法复制为图片。");
  }

  const canvas = document.createElement("canvas");
  canvas.width = scaledWidth;
  canvas.height = scaledHeight;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("无法创建图片画布。");
  }

  context.scale(outputPixelRatio, outputPixelRatio);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);

  const coveredCells = new Set<string>();
  let y = 0;
  for (let rowIndex = range.sri; rowIndex <= range.eri; rowIndex += 1) {
    let x = 0;
    const rowHeight = rowHeights[rowIndex - range.sri] ?? defaultRowHeight;

    for (let colIndex = range.sci; colIndex <= range.eci; colIndex += 1) {
      const colWidth = columnWidths[colIndex - range.sci] ?? defaultColumnWidth;
      const cellKey = `${rowIndex}:${colIndex}`;

      if (!coveredCells.has(cellKey)) {
        const cell = sheet.getCell?.(rowIndex, colIndex) ?? null;
        const cellStyle = sheet.getCellStyleOrDefault?.(rowIndex, colIndex) ?? {};
        const rect = resolveCellRect(range, rowIndex, colIndex, x, y, colWidth, rowHeight, rowHeights, columnWidths, cell);

        markMergedCells(coveredCells, rowIndex, colIndex, rect.rowSpan, rect.colSpan);
        drawCell(context, rect, cell, cellStyle);
      }

      x += colWidth;
    }

    y += rowHeight;
  }

  return canvas;
}

function collectSizes(start: number, end: number, getSize: (index: number) => number) {
  const sizes: number[] = [];
  for (let index = start; index <= end; index += 1) {
    const size = getSize(index);
    sizes.push(Number.isFinite(size) && size > 0 ? size : 1);
  }
  return sizes;
}

function resolveCellRect(
  range: ExcelRange,
  rowIndex: number,
  colIndex: number,
  x: number,
  y: number,
  width: number,
  height: number,
  rowHeights: number[],
  columnWidths: number[],
  cell: ExcelCell | null,
) {
  const [mergeRows = 0, mergeCols = 0] = cell?.merge ?? [];
  const rowSpan = Math.min(mergeRows + 1, range.eri - rowIndex + 1);
  const colSpan = Math.min(mergeCols + 1, range.eci - colIndex + 1);

  return {
    colSpan,
    height: sum(rowHeights.slice(rowIndex - range.sri, rowIndex - range.sri + rowSpan)) || height,
    rowSpan,
    width: sum(columnWidths.slice(colIndex - range.sci, colIndex - range.sci + colSpan)) || width,
    x,
    y,
  };
}

function markMergedCells(coveredCells: Set<string>, rowIndex: number, colIndex: number, rowSpan: number, colSpan: number) {
  for (let rowOffset = 0; rowOffset < rowSpan; rowOffset += 1) {
    for (let colOffset = 0; colOffset < colSpan; colOffset += 1) {
      if (rowOffset === 0 && colOffset === 0) continue;
      coveredCells.add(`${rowIndex + rowOffset}:${colIndex + colOffset}`);
    }
  }
}

function drawCell(
  context: CanvasRenderingContext2D,
  rect: { height: number; width: number; x: number; y: number },
  cell: ExcelCell | null,
  style: ExcelStyle,
) {
  context.save();
  context.fillStyle = style.bgcolor || "#ffffff";
  context.fillRect(rect.x, rect.y, rect.width, rect.height);
  drawCellText(context, rect, cell, style);
  drawCellBorder(context, rect, style);
  context.restore();
}

function drawCellText(
  context: CanvasRenderingContext2D,
  rect: { height: number; width: number; x: number; y: number },
  cell: ExcelCell | null,
  style: ExcelStyle,
) {
  const text = cell?.text == null ? "" : String(cell.text);
  if (!text) return;

  const font = style.font ?? {};
  const fontSize = Math.max(8, Math.round((font.size ?? 10) * 1.333));
  const fontFamily = font.name || "Arial";
  const fontWeight = font.bold ? "700" : "400";
  const fontStyle = font.italic ? "italic" : "normal";
  const paddingX = 6;
  const lineHeight = Math.ceil(fontSize * 1.35);
  const maxTextWidth = Math.max(1, rect.width - paddingX * 2);

  context.font = `${fontStyle} ${fontWeight} ${fontSize}px ${quoteFontFamily(fontFamily)}`;
  context.fillStyle = style.color || "#0a0a0a";
  context.textBaseline = "top";
  context.textAlign = resolveCanvasAlign(style.align);

  const lines = style.textwrap ? wrapText(context, text, maxTextWidth) : text.split(/\r?\n/).slice(0, 1);
  const textHeight = lines.length * lineHeight;
  let y = rect.y + resolveTextOffsetY(style.valign, rect.height, textHeight);
  const x = resolveTextX(style.align, rect.x, rect.width, paddingX);

  context.beginPath();
  context.rect(rect.x + 1, rect.y + 1, Math.max(1, rect.width - 2), Math.max(1, rect.height - 2));
  context.clip();

  for (const line of lines) {
    if (y + lineHeight > rect.y + rect.height) break;
    context.fillText(line, x, y);
    y += lineHeight;
  }
}

function drawCellBorder(
  context: CanvasRenderingContext2D,
  rect: { height: number; width: number; x: number; y: number },
  style: ExcelStyle,
) {
  const defaultColor = "#d9d9d9";
  drawLine(context, rect.x, rect.y, rect.x + rect.width, rect.y, style.border?.top?.[1] || defaultColor);
  drawLine(context, rect.x, rect.y + rect.height, rect.x + rect.width, rect.y + rect.height, style.border?.bottom?.[1] || defaultColor);
  drawLine(context, rect.x, rect.y, rect.x, rect.y + rect.height, style.border?.left?.[1] || defaultColor);
  drawLine(context, rect.x + rect.width, rect.y, rect.x + rect.width, rect.y + rect.height, style.border?.right?.[1] || defaultColor);
}

function drawLine(context: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string) {
  context.beginPath();
  context.strokeStyle = color;
  context.lineWidth = 1;
  context.moveTo(Math.round(x1) + 0.5, Math.round(y1) + 0.5);
  context.lineTo(Math.round(x2) + 0.5, Math.round(y2) + 0.5);
  context.stroke();
}

function wrapText(context: CanvasRenderingContext2D, text: string, maxWidth: number) {
  const lines: string[] = [];
  for (const paragraph of text.split(/\r?\n/)) {
    let currentLine = "";
    for (const char of paragraph) {
      const nextLine = `${currentLine}${char}`;
      if (currentLine && context.measureText(nextLine).width > maxWidth) {
        lines.push(currentLine);
        currentLine = char;
      } else {
        currentLine = nextLine;
      }
    }
    lines.push(currentLine);
  }
  return lines;
}

function resolveCanvasAlign(align: ExcelStyle["align"]): CanvasTextAlign {
  if (align === "center") return "center";
  if (align === "right") return "right";
  return "left";
}

function resolveTextX(align: ExcelStyle["align"], x: number, width: number, paddingX: number) {
  if (align === "center") return x + width / 2;
  if (align === "right") return x + width - paddingX;
  return x + paddingX;
}

function resolveTextOffsetY(valign: ExcelStyle["valign"], height: number, textHeight: number) {
  if (valign === "top") return 4;
  if (valign === "bottom") return Math.max(4, height - textHeight - 4);
  return Math.max(4, (height - textHeight) / 2);
}

function quoteFontFamily(fontFamily: string) {
  return fontFamily.includes(" ") ? `"${fontFamily.replaceAll('"', "")}"` : fontFamily;
}

function canvasToPngBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("选区图片生成失败。"));
      }
    }, "image/png");
  });
}

async function writeCanvasPngToClipboard(canvas: HTMLCanvasElement) {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("当前环境不支持复制图片到剪贴板。");
  }

  await navigator.clipboard.write([
    new ClipboardItem({
      "image/png": canvasToPngBlob(canvas),
    }),
  ]);
}

function collectExcelSelectionCells(sheet: RuntimeSheetData, range: ExcelRange) {
  const rows: string[][] = [];
  for (let rowIndex = range.sri; rowIndex <= range.eri; rowIndex += 1) {
    const row: string[] = [];
    for (let colIndex = range.sci; colIndex <= range.eci; colIndex += 1) {
      const text = sheet.getCell?.(rowIndex, colIndex)?.text;
      row.push(text == null ? "" : String(text));
    }
    rows.push(row);
  }
  return rows;
}

function formatExcelRangeAddress(range: ExcelRange) {
  return `${columnIndexToName(range.sci)}${range.sri + 1}:${columnIndexToName(range.eci)}${range.eri + 1}`;
}

function columnIndexToName(index: number) {
  let value = index + 1;
  let name = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = `${String.fromCharCode(65 + remainder)}${name}`;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

function buildExcelSelectionImageFileName(
  sourceFileName: string,
  sheetName: string,
  rangeAddress: string,
) {
  const sourceBaseName = sourceFileName.replace(/\.[^.]*$/, "") || "excel_selection";
  const rawName = `${sourceBaseName}__${sheetName}__${rangeAddress.replace(":", "_")}`;
  const safeName = rawName
    .replace(/[<>:"/\\|?*\x00-\x1F]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 140) || "excel_selection";
  return `${safeName}.png`;
}

function releaseCanvas(canvas: HTMLCanvasElement) {
  canvas.width = 0;
  canvas.height = 0;
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}
