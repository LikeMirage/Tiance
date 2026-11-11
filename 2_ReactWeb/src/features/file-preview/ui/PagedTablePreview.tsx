import { useEffect, useRef, useState } from "react";
import { useDocumentReadingValue, useDocumentReadingScroll } from "../../../entities/editor/model/documentReadingState";

import { readSpreadsheetPage, type FilePreviewInspection, type SpreadsheetPage } from "../model/filePreview";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { renderSheetRangeToPngFile, type ExcelRange, type ExcelSelectionImageReferencePayload } from "../../office-preview/ui/excelSelectionImage";
import { useDocumentRevealRequest } from "../../../entities/editor/model/documentRevealContext";
import type { DocumentRevealRequest } from "../../../entities/editor/model/documentReveal";
import { spreadsheetReferenceRange, spreadsheetReferenceMatches } from "../../office-preview/ui/spreadsheetReferenceSelection";

export function PagedTablePreview({
  src, fileName, displayPath, inspection, zoom, onLoadingVisibleChange, onCreateSelectionImageReference, onMissing,
}: {
  src: string; fileName: string; displayPath: string; inspection: FilePreviewInspection; zoom: number;
  onLoadingVisibleChange: (loading: boolean) => void;
  onCreateSelectionImageReference: ((payload: ExcelSelectionImageReferencePayload) => Promise<void>) | null;
  onMissing?: (() => void) | null;
}) {
  const [sheetName, setSheetName] = useDocumentReadingValue("excel:sheet", inspection.sheets?.[0]?.name ?? "");
  const [savedRow, setRow] = useDocumentReadingValue("excel:row", 0);
  const [savedColumn, setColumn] = useDocumentReadingValue("excel:column", 0);
  const [page, setPage] = useState<SpreadsheetPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<ExcelRange | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const dragging = useRef(false);
  const onMissingRef = useRef(onMissing);
  onMissingRef.current = onMissing;
  const scrollerRef = useRef<HTMLDivElement>(null);
  const reveal = useDocumentRevealRequest();
  const [pendingRange, setPendingRange] = useState<{ request: DocumentRevealRequest; range: ExcelRange; sheetName: string } | null>(null);
  const sheets = inspection.sheets ?? [];
  const sheet = Math.max(0, sheets.findIndex((item) => item.name === sheetName));
  const sheetInfo = sheets[sheet];
  const rowCount = inspection.page_rows ?? 50;
  const columnCount = inspection.page_columns ?? 20;
  const row = Math.min(savedRow, Math.max(0, Math.ceil((sheetInfo?.rows ?? 0) / rowCount) - 1) * rowCount);
  const column = Math.min(savedColumn, Math.max(0, Math.ceil((sheetInfo?.columns ?? 0) / columnCount) - 1) * columnCount);
  const current = page?.row_start === row && page.column_start === column && page.sheet_name === sheetInfo?.name ? page : null;
  useDocumentReadingScroll("excel-paged", scrollerRef, Boolean(current), inspection.version);

  useEffect(() => {
    if (!reveal || reveal.signal.aborted || reveal.target.type !== "reference_image"
      || reveal.target.reference.source !== "xlsx_range") return;
    setRange(null); setPendingRange(null);
    const reference = reveal.target.reference;
    const target = spreadsheetReferenceRange(reference);
    const sheetIndex = inspection.sheets?.findIndex(item => item.name === reference.sheetName) ?? -1;
    const info = inspection.sheets?.[sheetIndex];
    if (!target || !info || target.eri >= info.rows || target.eci >= info.columns) {
      reveal.complete({ type: "reference", selected: false }); return;
    }
    let cancelled = false;
    void (async () => {
      const pages: SpreadsheetPage[] = [];
      for (let r = Math.floor(target.sri / rowCount) * rowCount; r <= target.eri; r += rowCount) {
        for (let c = Math.floor(target.sci / columnCount) * columnCount; c <= target.eci; c += columnCount) {
          const part = await readSpreadsheetPage(src, inspection.version!, sheetIndex, r, c, reveal.signal);
          if (cancelled || reveal.signal.aborted) return;
          pages.push(part);
        }
      }
      const matches = spreadsheetReferenceMatches(reference, target, (r, c) => {
        const part = pages.find(p => p.row_start === Math.floor(r / rowCount) * rowCount
          && p.column_start === Math.floor(c / columnCount) * columnCount);
        return part?.values[r - part.row_start]?.[c - part.column_start];
      });
      if (!matches) { reveal.complete({ type: "reference", selected: false }); return; }
      setSheetName(info.name); setRow(Math.floor(target.sri / rowCount) * rowCount);
      setColumn(Math.floor(target.sci / columnCount) * columnCount);
      setPendingRange({ request: reveal, range: target, sheetName: info.name });
    })().catch(error => { if (!cancelled && !reveal.signal.aborted) reveal.fail(error); });
    return () => { cancelled = true; };
  }, [reveal, src, inspection, rowCount, columnCount, setSheetName, setRow, setColumn]);

  useEffect(() => {
    if (!pendingRange || pendingRange.request !== reveal || reveal.signal.aborted || !current
      || current.sheet_name !== pendingRange.sheetName
      || current.row_start !== Math.floor(pendingRange.range.sri / rowCount) * rowCount
      || current.column_start !== Math.floor(pendingRange.range.sci / columnCount) * columnCount) return;
    setRange(pendingRange.range);
    const frame = requestAnimationFrame(() => {
      if (reveal.signal.aborted) return;
      scrollerRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "center", inline: "center" });
      reveal.complete({ type: "reference", selected: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [pendingRange, reveal, current, rowCount, columnCount]);

  useEffect(() => {
    const run = ++generation.current;
    const controller = new AbortController();
    setPage(null); setRange(null); setMenu(null); setError(null); setBusy(false);
    onLoadingVisibleChange(true);
    void readSpreadsheetPage(src, inspection.version!, sheet, row, column, controller.signal).then(
      (result) => { if (!controller.signal.aborted) setPage(result); },
      (reason: unknown) => {
        if (!controller.signal.aborted) {
          if (reason && typeof reason === "object" && "status" in reason && reason.status === 404) onMissingRef.current?.();
          setError(reason instanceof Error ? reason.message : "工作表读取失败。");
        }
      },
    ).finally(() => { if (generation.current === run && !controller.signal.aborted) onLoadingVisibleChange(false); });
    return () => { generation.current += 1; controller.abort(); };
  }, [src, inspection.version, sheet, row, column, attempt, onLoadingVisibleChange]);
  useEffect(() => {
    const stop = () => { dragging.current = false; };
    window.addEventListener("pointerup", stop);
    return () => window.removeEventListener("pointerup", stop);
  }, []);

  const selectedRange = range ? {
    sri: Math.min(range.sri, range.eri), eri: Math.max(range.sri, range.eri),
    sci: Math.min(range.sci, range.eci), eci: Math.max(range.sci, range.eci),
  } : null;
  const exportSelection = async (reference: boolean) => {
    if (!current || !selectedRange || busy) return;
    const run = generation.current;
    setBusy(true); setMenu(null); setError(null);
    try {
      const result = await renderSheetRangeToPngFile({
        name: current.sheet_name,
        getCell: (r, c) => ({ text: current.values[r - row]?.[c - column] ?? "" }),
        cols: { getWidth: () => 120 }, rows: { getHeight: () => 26 },
      }, selectedRange, fileName);
      if (generation.current !== run) return;
      if (reference) {
        await onCreateSelectionImageReference?.({ ...result, sourceDisplayPath: displayPath, sourceFileName: fileName });
      } else {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": result.file })]);
      }
    } catch (reason) {
      if (generation.current === run) setError(reason instanceof Error ? reason.message : "选区处理失败。");
    } finally {
      if (generation.current === run) setBusy(false);
    }
  };
  return (
    <div className={inspection.delimited ? "spreadsheet-pages spreadsheet-pages--delimited" : "spreadsheet-pages"}>
      <div className="spreadsheet-pages__controls">
        {inspection.delimited ? null : <select aria-label="工作表" value={sheet} onChange={(event) => {
          setSheetName(sheets[Number(event.target.value)]?.name ?? ""); setRow(0); setColumn(0);
        }}>{sheets.map((item, index) => <option key={index} value={index}>{item.name}</option>)}</select>}
        <button disabled={row === 0} onClick={() => setRow(Math.max(0, row - rowCount))}>上一页行</button>
        <span>行 {sheetInfo?.rows ? row + 1 : 0}–{Math.min(row + rowCount, sheetInfo?.rows ?? 0)} / {sheetInfo?.rows}</span>
        <button disabled={row + rowCount >= (sheetInfo?.rows ?? 0)} onClick={() => setRow(row + rowCount)}>下一页行</button>
        <button disabled={column === 0} onClick={() => setColumn(Math.max(0, column - columnCount))}>前一组列</button>
        <span>列 {sheetInfo?.columns ? `${columnName(column)}–${columnName(Math.min(column + columnCount, sheetInfo.columns) - 1)}` : "0"}</span>
        <button disabled={column + columnCount >= (sheetInfo?.columns ?? 0)} onClick={() => setColumn(column + columnCount)}>后一组列</button>
        {selectedRange && onCreateSelectionImageReference
          ? <button disabled={busy || !current} onClick={() => void exportSelection(true)}>引用选区</button> : null}
      </div>
      {error ? <div role="alert" className="spreadsheet-pages__note">{error} <button onClick={() => setAttempt(attempt + 1)}>重试</button></div> : null}
      {!current && !error ? <LoadingStrip ariaLabel="正在读取此页" mode="overlay" surface="dark" visual="ring" /> : null}
      {current && !sheetInfo?.rows ? <div className="spreadsheet-pages__note">文件为空。</div> : null}
      <div className="spreadsheet-pages__scroll" tabIndex={0} ref={scrollerRef}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && selectedRange) {
            event.preventDefault(); void exportSelection(false);
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault(); event.stopPropagation();
          if (selectedRange) setMenu({ x: event.clientX, y: event.clientY });
        }}>
        {current ? <table style={{ fontSize: "12px", zoom }}>
          <thead><tr><th></th>{Array.from({ length: Math.min(columnCount, (sheetInfo?.columns ?? 0) - column) }, (_, c) =>
            <th key={c}>{columnName(column + c)}</th>)}</tr></thead>
          <tbody>{current.values.slice(0, Math.min(rowCount, (sheetInfo?.rows ?? 0) - row)).map((cells, r) =>
            <tr key={row + r}><th>{row + r + 1}</th>{cells.slice(0, Math.min(columnCount, (sheetInfo?.columns ?? 0) - column)).map((value, c) =>
              <td key={column + c} title={value} aria-selected={Boolean(selectedRange
                && row + r >= selectedRange.sri && row + r <= selectedRange.eri
                && column + c >= selectedRange.sci && column + c <= selectedRange.eci)}
                onPointerDown={(event) => {
                  if (event.button !== 0) return;
                  event.preventDefault(); dragging.current = true;
                  scrollerRef.current?.focus({ preventScroll: true });
                  setRange(event.shiftKey && range
                    ? { ...range, eri: row + r, eci: column + c }
                    : { sri: row + r, eri: row + r, sci: column + c, eci: column + c });
                }}
                onPointerEnter={() => {
                  if (dragging.current) setRange((previous) => previous ? { ...previous, eri: row + r, eci: column + c } : null);
                }}>{value}</td>)}</tr>)}</tbody>
        </table> : null}
      </div>
      {menu ? <ContextMenu position={menu} onClose={() => setMenu(null)}>
        <ContextMenuItem disabled={busy} onSelect={() => void exportSelection(false)}>复制选区图片</ContextMenuItem>
        {onCreateSelectionImageReference ? <ContextMenuItem disabled={busy} onSelect={() => void exportSelection(true)}>引用选区到对话</ContextMenuItem> : null}
      </ContextMenu> : null}
    </div>
  );
}

function columnName(index: number) {
  let name = "";
  for (let number = index + 1; number > 0; number = Math.floor((number - 1) / 26)) {
    name = String.fromCharCode(65 + (number - 1) % 26) + name;
  }
  return name;
}
