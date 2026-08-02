import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { JsExcelPreview, Options as JsExcelPreviewOptions } from "@js-preview/excel";
import "@js-preview/excel/lib/index.css";

import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type { OfficeLoadingVisibilityChange } from "./officePreviewTypes";
import { officePreviewMinimumLoadingMs } from "./officePreviewTypes";
import { removeUnsupportedExcelDrawings } from "./excelPreviewBuffer";
import {
  copyExcelSelectionAsImage,
  renderExcelSelectionToPngFile,
  type ExcelSelectionImageReferencePayload,
} from "./excelSelectionImage";

type ExcelPreviewProps = {
  displayPath: string;
  fileName: string;
  onCreateSelectionImageReference?: ((payload: ExcelSelectionImageReferencePayload) => Promise<void>) | null;
  onLoadingVisibleChange?: OfficeLoadingVisibilityChange;
  onMissing?: (() => void) | null;
  onWheelZoom: (deltaY: number) => void;
  src: string | null;
  zoom: number;
};

type LoadState = "idle" | "loading" | "ready" | "error";
type ExcelRecord = Record<string, unknown>;
type ExcelWorkbookData = ExcelSheetData[];
type ExcelSheetData = ExcelRecord & {
  cols?: ExcelIndexedCollection;
  rows?: ExcelIndexedCollection;
  styles?: unknown[];
};
type ExcelIndexedCollection = ExcelRecord & {
  len?: unknown;
};
type ExcelPreviewOptions = JsExcelPreviewOptions & {
  transformData?: (workbookData: ExcelWorkbookData) => ExcelWorkbookData;
};
type InternalExcelPreviewer = JsExcelPreview & {
  sheetIndex?: number;
  xs?: {
    bottombar?: {
      swapFunc?: (index: number) => void;
    };
    loadData?: (data: ExcelWorkbookData) => void;
    reRender?: () => void;
  };
};

type SelectionReferenceMenuState = {
  x: number;
  y: number;
} | null;

const defaultExcelFontName = "Microsoft YaHei";
const defaultExcelFontSize = 10;
const excelZoomRefreshDelayMs = 180;

export function ExcelPreview({
  displayPath,
  fileName,
  onCreateSelectionImageReference = null,
  onLoadingVisibleChange,
  onMissing = null,
  onWheelZoom,
  src,
  zoom,
}: ExcelPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const onMissingRef = useRef(onMissing);
  const shellRef = useRef<HTMLDivElement>(null);
  const previewerRef = useRef<JsExcelPreview | null>(null);
  const isExcelInteractionActiveRef = useRef(false);
  const isCreatingSelectionReferenceRef = useRef(false);
  const selectionReferenceRunIdRef = useRef(0);
  const workbookDataRef = useRef<ExcelWorkbookData | null>(null);
  const zoomRef = useRef(zoom);
  const [copyErrorMessage, setCopyErrorMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isCreatingSelectionReference, setIsCreatingSelectionReference] = useState(false);
  const [selectionReferenceMenu, setSelectionReferenceMenu] = useState<SelectionReferenceMenuState>(null);
  const [state, setState] = useState<LoadState>(() => (src ? "loading" : "idle"));
  const isLoadingVisible = useMinimumLoading(state === "loading", officePreviewMinimumLoadingMs);
  const excelShellClassName = [
    "office-preview__excel-shell",
    state === "ready" && !isLoadingVisible ? "" : "office-preview__excel-shell--loading",
  ].filter(Boolean).join(" ");

  const createPreviewOptions = (): ExcelPreviewOptions => ({
    minColLength: 20,
    minRowLength: 40,
    showContextmenu: false,
    transformData: (workbookData) => {
      workbookDataRef.current = normalizeExcelWorkbookData(cloneExcelWorkbookData(workbookData));
      return scaleExcelWorkbookData(workbookDataRef.current, zoomRef.current);
    },
  });

  useEffect(() => {
    onMissingRef.current = onMissing;
  }, [onMissing]);

  useEffect(() => {
    onLoadingVisibleChange?.(isLoadingVisible);
  }, [isLoadingVisible, onLoadingVisibleChange]);

  useEffect(() => {
    selectionReferenceRunIdRef.current += 1;
    isCreatingSelectionReferenceRef.current = false;
    setIsCreatingSelectionReference(false);
    setSelectionReferenceMenu(null);

    return () => {
      selectionReferenceRunIdRef.current += 1;
      isCreatingSelectionReferenceRef.current = false;
    };
  }, [displayPath, fileName, src]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return undefined;

    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      onWheelZoom(event.deltaY);
    };

    shell.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => shell.removeEventListener("wheel", handleWheel, { capture: true });
  }, [onWheelZoom]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return undefined;

    const updateExcelActiveState = (event: Event) => {
      isExcelInteractionActiveRef.current = event.target instanceof Node && shell.contains(event.target);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isExcelInteractionActiveRef.current || state !== "ready") return;
      if (event.altKey || event.shiftKey || event.repeat) return;
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "c") return;

      event.preventDefault();
      event.stopPropagation();
      void copyExcelSelectionAsImage(previewerRef.current)
        .then(() => setCopyErrorMessage(null))
        .catch((err: unknown) => {
          setCopyErrorMessage(err instanceof Error ? err.message : "复制 Excel 选区图片失败。");
        });
    };

    document.addEventListener("pointerdown", updateExcelActiveState, true);
    document.addEventListener("focusin", updateExcelActiveState, true);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", updateExcelActiveState, true);
      document.removeEventListener("focusin", updateExcelActiveState, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [state]);

  useEffect(() => {
    zoomRef.current = zoom;
    if (state !== "ready" || !workbookDataRef.current) return undefined;

    let frameId: number | null = null;
    const timeoutId = window.setTimeout(() => {
      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        if (state !== "ready" || !workbookDataRef.current) return;
        refreshExcelPreview(previewerRef.current, scaleExcelWorkbookData(workbookDataRef.current, zoom));
      });
    }, excelZoomRefreshDelayMs);

    return () => {
      window.clearTimeout(timeoutId);
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [state, zoom]);

  useEffect(() => {
    const container = containerRef.current;
    if (!src || !container) {
      safeDestroyExcelPreviewer(previewerRef.current);
      previewerRef.current = null;
      workbookDataRef.current = null;
      setCopyErrorMessage(null);
      setErrorMessage(null);
      setSelectionReferenceMenu(null);
      setState("idle");
      container?.replaceChildren();
      return undefined;
    }

    let isCancelled = false;
    const controller = new AbortController();

    let previewer: JsExcelPreview | null = null;

    const load = async () => {
      setCopyErrorMessage(null);
      setErrorMessage(null);
      setSelectionReferenceMenu(null);
      setState("loading");
      container.replaceChildren();

      try {
        const [{ default: jsPreviewExcel }, response] = await Promise.all([
          import("@js-preview/excel"),
          fetch(src, { signal: controller.signal }),
        ]);
        if (isCancelled) return;
        if (!response.ok) {
          if (response.status === 404) {
            onMissingRef.current?.();
            return;
          }
          throw new Error(`文件读取失败：${response.status}`);
        }

        const arrayBuffer = await response.arrayBuffer();
        if (isCancelled) return;
        const preparedWorkbook = await removeUnsupportedExcelDrawings(arrayBuffer);
        if (isCancelled) return;

        previewer = jsPreviewExcel.init(container, createPreviewOptions());
        previewerRef.current = previewer;

        try {
          await previewer.preview(preparedWorkbook.buffer);
        } catch (previewError) {
          if (!isUnsupportedDrawingError(previewError)) {
            throw previewError;
          }

          if (preparedWorkbook.removedUnsupportedDrawingCount > 0 || isCancelled) {
            throw previewError;
          }

          const cleanupResult = await removeUnsupportedExcelDrawings(arrayBuffer);
          if (cleanupResult.removedUnsupportedDrawingCount <= 0 || isCancelled) {
            throw previewError;
          }

          safeDestroyExcelPreviewer(previewer);
          if (previewerRef.current === previewer) {
            previewerRef.current = null;
          }
          container.replaceChildren();

          previewer = jsPreviewExcel.init(container, createPreviewOptions());
          previewerRef.current = previewer;
          await previewer.preview(cleanupResult.buffer);
        }
        if (isCancelled) return;
        setState("ready");
      } catch (err) {
        if (isCancelled || controller.signal.aborted) return;
        safeDestroyExcelPreviewer(previewer);
        if (previewerRef.current === previewer) {
          previewerRef.current = null;
        }
        workbookDataRef.current = null;
        container.replaceChildren();
        setErrorMessage(formatExcelPreviewError(err));
        setState("error");
      }
    };

    void load();

    return () => {
      isCancelled = true;
      controller.abort();
      safeDestroyExcelPreviewer(previewer);
      if (previewerRef.current === previewer) {
        previewerRef.current = null;
      }
      workbookDataRef.current = null;
      container.replaceChildren();
    };
  }, [src]);

  const handleContextMenu = (event: MouseEvent<HTMLElement>) => {
    if (state !== "ready" || !onCreateSelectionImageReference) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectionReferenceMenu({
      x: event.clientX,
      y: event.clientY,
    });
  };

  const createSelectionReference = () => {
    if (state !== "ready" || !onCreateSelectionImageReference || isCreatingSelectionReferenceRef.current) return;

    const currentRunId = selectionReferenceRunIdRef.current;
    const currentPreviewer = previewerRef.current;
    const sourceDisplayPath = displayPath;
    const sourceFileName = fileName;

    isCreatingSelectionReferenceRef.current = true;
    setIsCreatingSelectionReference(true);
    setCopyErrorMessage(null);
    setSelectionReferenceMenu(null);

    void renderExcelSelectionToPngFile(currentPreviewer, sourceFileName)
      .then(async (selection) => {
        if (selectionReferenceRunIdRef.current !== currentRunId) return;

        await onCreateSelectionImageReference({
          ...selection,
          sourceDisplayPath,
          sourceFileName,
        });
      })
      .then(() => {
        if (selectionReferenceRunIdRef.current === currentRunId) {
          setCopyErrorMessage(null);
        }
      })
      .catch((err: unknown) => {
        if (selectionReferenceRunIdRef.current === currentRunId) {
          setCopyErrorMessage(err instanceof Error ? err.message : "引用 Excel 选区失败。");
        }
      })
      .finally(() => {
        if (selectionReferenceRunIdRef.current === currentRunId) {
          isCreatingSelectionReferenceRef.current = false;
          setIsCreatingSelectionReference(false);
        }
      });
  };

  return (
    <main className="office-preview__body">
      {isLoadingVisible ? (
        <LoadingStrip
          ariaLabel="正在加载 Excel 工作簿"
          className="office-preview__excel-loading"
          mode="fill"
          surface="dark"
          visual="ring"
        />
      ) : null}
      {!isLoadingVisible && state === "error" ? (
        <div className="office-preview__status office-preview__status--error">{errorMessage}</div>
      ) : null}
      {!isLoadingVisible && copyErrorMessage ? (
        <div className="office-preview__status office-preview__status--error">{copyErrorMessage}</div>
      ) : null}
      <div className={excelShellClassName} ref={shellRef} onContextMenu={handleContextMenu}>
        <div className="office-preview__excel-host" ref={containerRef} />
      </div>
      {selectionReferenceMenu ? (
        <ContextMenu
          onClose={() => setSelectionReferenceMenu(null)}
          position={{ x: selectionReferenceMenu.x, y: selectionReferenceMenu.y }}
        >
          <ContextMenuItem disabled={isCreatingSelectionReference} onSelect={createSelectionReference}>
            {isCreatingSelectionReference ? "正在引用选区..." : "引用选区到对话"}
          </ContextMenuItem>
        </ContextMenu>
      ) : null}
      {!isLoadingVisible && state === "idle" ? <div className="office-preview__empty">Excel 文件地址无效。</div> : null}
    </main>
  );
}

function refreshExcelPreview(previewer: JsExcelPreview | null, workbookData: ExcelWorkbookData) {
  const internalPreviewer = previewer as InternalExcelPreviewer | null;
  if (!internalPreviewer?.xs?.loadData) return;

  const sheetIndex = typeof internalPreviewer.sheetIndex === "number" ? internalPreviewer.sheetIndex : 0;
  internalPreviewer.xs.loadData(workbookData);
  internalPreviewer.xs.bottombar?.swapFunc?.(sheetIndex);
  internalPreviewer.xs.reRender?.();
}

function scaleExcelWorkbookData(workbookData: ExcelWorkbookData, zoom: number): ExcelWorkbookData {
  const scaledWorkbookData = cloneExcelWorkbookData(workbookData);

  for (const sheet of scaledWorkbookData) {
    scaleExcelIndexedSize(sheet.rows, "height", zoom);
    scaleExcelIndexedSize(sheet.cols, "width", zoom);
    scaleExcelStyles(sheet.styles, zoom);
  }

  return scaledWorkbookData;
}

function normalizeExcelWorkbookData(workbookData: ExcelWorkbookData): ExcelWorkbookData {
  for (const [index, sheet] of workbookData.entries()) {
    if (typeof sheet.name !== "string" || !sheet.name.trim()) {
      sheet.name = `Sheet${index + 1}`;
    }
    normalizeExcelStyles(sheet.styles);
  }

  return workbookData;
}

function normalizeExcelStyles(styles: unknown[] | undefined) {
  if (!styles) return;

  for (let index = 0; index < styles.length; index += 1) {
    const style = styles[index];
    if (!isExcelRecord(style)) {
      styles[index] = {
        font: {
          name: defaultExcelFontName,
          size: defaultExcelFontSize,
        },
      };
      continue;
    }

    const font = isExcelRecord(style.font) ? style.font : {};
    style.font = font;
    if (typeof font.name !== "string" || !font.name.trim()) {
      font.name = defaultExcelFontName;
    }

    const fontSize = font.size;
    if (typeof fontSize !== "number" || !Number.isFinite(fontSize) || fontSize <= 0) {
      font.size = defaultExcelFontSize;
    }
  }
}

function scaleExcelIndexedSize(collection: ExcelIndexedCollection | undefined, key: "height" | "width", zoom: number) {
  if (!collection) return;

  for (const [entryKey, entryValue] of Object.entries(collection)) {
    if (entryKey === "len" || !isExcelRecord(entryValue)) continue;
    const value = entryValue[key];
    if (typeof value !== "number" || value <= 0.5) continue;
    entryValue[key] = clampExcelSize(value * zoom, key);
  }
}

function scaleExcelStyles(styles: unknown[] | undefined, zoom: number) {
  if (!styles) return;

  for (const style of styles) {
    if (!isExcelRecord(style) || !isExcelRecord(style.font)) continue;
    const size = style.font.size;
    if (typeof size !== "number") continue;
    style.font.size = Math.max(6, Math.min(72, Math.round(size * zoom * 100) / 100));
  }
}

function clampExcelSize(value: number, key: "height" | "width") {
  const min = key === "height" ? 8 : 18;
  const max = key === "height" ? 240 : 640;
  return Math.max(min, Math.min(max, Math.round(value * 100) / 100));
}

function cloneExcelWorkbookData(workbookData: ExcelWorkbookData): ExcelWorkbookData {
  if (typeof structuredClone === "function") {
    return structuredClone(workbookData);
  }

  return JSON.parse(JSON.stringify(workbookData)) as ExcelWorkbookData;
}

function isExcelRecord(value: unknown): value is ExcelRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeDestroyExcelPreviewer(previewer: JsExcelPreview | null) {
  try {
    previewer?.destroy();
  } catch (err) {
    if (!isExcelDestroyError(err)) {
      throw err;
    }
  }
}

function isExcelDestroyError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return error.message.includes("reading 'disconnect'") || error.message.includes('reading "disconnect"');
}

function isUnsupportedDrawingError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return error.message.includes("reading 'anchors'") || error.message.includes('reading "anchors"');
}

function formatExcelPreviewError(error: unknown) {
  if (isExcelInternalPreviewError(error)) {
    return "Excel 文件结构不完整或包含预览器暂不支持的内容，无法直接预览。可用 Excel / WPS 打开检查。";
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Excel 文件预览失败。";
}

function isExcelInternalPreviewError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return (
    error.message.includes("Cannot read properties of undefined") ||
    error.message.includes("Cannot read properties of null")
  );
}
