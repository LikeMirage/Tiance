import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import {
  CaretLeft,
  CaretRight,
  FilePdf,
  FolderOpen,
  FrameCorners,
  SidebarSimple,
} from "@phosphor-icons/react";

import {
  renderPdfPageToPngFile,
  type PdfPageImageReferencePayload,
} from "../model/pdfPageImage";
import {
  loadPdfJs,
  type PdfDocumentProxy,
  type PdfJsLib,
  type PdfLoadingTask,
} from "../model/pdfjsLoader";
import { PdfPageView } from "./PdfPageView";
import { PdfThumbnailStrip } from "./PdfThumbnailStrip";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { usePanZoomViewport } from "../../../shared/model/pan-zoom/usePanZoomViewport";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { PreviewZoomControl } from "../../../shared/ui/preview-zoom-control";
import "./pdf-preview.css";

type PdfPreviewProps = {
  displayPath: string;
  fileName: string;
  onCreatePageImageReference?: ((payload: PdfPageImageReferencePayload) => Promise<void>) | null;
  onMissing?: (() => void) | null;
  onRevealFile?: (() => Promise<void>) | null;
  src: string | null;
};

const minScale = 0.25;
const maxScale = 4;

export function PdfPreview({
  displayPath,
  fileName,
  onCreatePageImageReference = null,
  onMissing = null,
  onRevealFile = null,
  src,
}: PdfPreviewProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fitMode, setFitMode] = useState<"width" | "custom">("width");
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isCreatingPageImage, setIsCreatingPageImage] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [numPages, setNumPages] = useState(0);
  const [pageImageMenu, setPageImageMenu] = useState<{ x: number; y: number } | null>(null);
  const [pdfDocument, setPdfDocument] = useState<PdfDocumentProxy | null>(null);
  const [pdfjs, setPdfjs] = useState<PdfJsLib | null>(null);
  const [scale, setScale] = useState(1);
  const currentPageRef = useRef(currentPage);
  const fitModeRef = useRef(fitMode);
  const fitWidthRequestIdRef = useRef(0);
  const pageSelectionRequestRef = useRef(0);
  const isLoadingVisible = useMinimumLoading(isLoading);

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    fitModeRef.current = fitMode;
    if (fitMode !== "width") {
      fitWidthRequestIdRef.current += 1;
    }
  }, [fitMode]);

  useEffect(() => {
    if (!src) {
      fitWidthRequestIdRef.current += 1;
      setErrorMessage("PDF 地址无效。");
      setPdfDocument(null);
      return undefined;
    }

    let isCancelled = false;
    let loadingTask: PdfLoadingTask | null = null;

    const loadDocument = async () => {
      pageSelectionRequestRef.current += 1;
      fitWidthRequestIdRef.current += 1;
      setIsLoading(true);
      setErrorMessage(null);
      setPdfDocument(null);
      setCurrentPage(1);
      setNumPages(0);

      try {
        const loadedPdfjs = await loadPdfJs();
        if (isCancelled) return;
        setPdfjs(loadedPdfjs);
        const currentLoadingTask = loadedPdfjs.getDocument({ url: src });
        loadingTask = currentLoadingTask;
        const loadedDocument = await currentLoadingTask.promise;
        if (isCancelled) {
          return;
        }
        setPdfDocument(loadedDocument);
        setNumPages(loadedDocument.numPages);
        setIsLoading(false);
      } catch (err) {
        if (isCancelled) return;
        setIsLoading(false);
        if (isPdfMissingError(err)) {
          onMissing?.();
          return;
        }
        setErrorMessage(err instanceof Error ? err.message : "PDF 加载失败。");
      }
    };

    void loadDocument();

    return () => {
      isCancelled = true;
      fitWidthRequestIdRef.current += 1;
      void loadingTask?.destroy();
    };
  }, [onMissing, src]);

  const clampPage = useCallback((pageNumber: number) => (
    Math.max(1, Math.min(numPages || 1, pageNumber))
  ), [numPages]);
  const setScaleIfChanged = useCallback((nextScale: number) => {
    setScale((currentScale) => (
      Math.abs(currentScale - nextScale) < 0.001 ? currentScale : nextScale
    ));
  }, []);

  const panZoom = usePanZoomViewport<HTMLDivElement, HTMLDivElement>({
    canInteract: Boolean(pdfDocument),
    maxZoom: maxScale,
    minZoom: minScale,
    onZoomChange(nextZoom) {
      pageSelectionRequestRef.current += 1;
      setFitMode("custom");
      setScale(nextZoom);
    },
    shouldStartPan: shouldStartPdfPan,
    zoom: scale,
  });

  const resolveFitWidthScale = useCallback(async (pageNumber: number) => {
    if (!pdfDocument || !panZoom.viewportRef.current) return;

    const page = await pdfDocument.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1 });
    const availableWidth = Math.max(280, panZoom.viewportRef.current.clientWidth - 56);
    return clampScale(availableWidth / viewport.width);
  }, [panZoom.viewportRef, pdfDocument]);

  const applyFitWidth = useCallback(async () => {
    const requestId = fitWidthRequestIdRef.current + 1;
    fitWidthRequestIdRef.current = requestId;
    const targetPage = currentPage;
    const nextScale = await resolveFitWidthScale(targetPage);
    if (nextScale === undefined) return;
    if (
      fitWidthRequestIdRef.current !== requestId ||
      fitModeRef.current !== "width" ||
      currentPageRef.current !== targetPage
    ) {
      return;
    }
    setScaleIfChanged(nextScale);
  }, [currentPage, resolveFitWidthScale, setScaleIfChanged]);

  useEffect(() => {
    if (fitMode !== "width") return;
    void applyFitWidth();
  }, [applyFitWidth, fitMode]);

  useEffect(() => {
    if (fitMode !== "width" || !panZoom.viewportRef.current) return undefined;

    const observer = new ResizeObserver(() => {
      void applyFitWidth();
    });
    observer.observe(panZoom.viewportRef.current);
    return () => observer.disconnect();
  }, [applyFitWidth, fitMode, panZoom.viewportRef]);

  const selectPage = useCallback((pageNumber: number) => {
    const nextPage = clampPage(pageNumber);
    if (nextPage === currentPage) return;

    const requestId = pageSelectionRequestRef.current + 1;
    pageSelectionRequestRef.current = requestId;
    const fitWidthRequestId = fitWidthRequestIdRef.current + 1;
    fitWidthRequestIdRef.current = fitWidthRequestId;

    if (fitMode !== "width") {
      setCurrentPage(nextPage);
      return;
    }

    void (async () => {
      let nextScale: number | undefined;
      try {
        nextScale = await resolveFitWidthScale(nextPage);
      } catch {
        nextScale = undefined;
      }

      if (pageSelectionRequestRef.current !== requestId) return;
      if (fitWidthRequestIdRef.current !== fitWidthRequestId || fitModeRef.current !== "width") return;
      if (nextScale !== undefined) {
        setScaleIfChanged(nextScale);
      }
      setCurrentPage(nextPage);
    })();
  }, [clampPage, currentPage, fitMode, resolveFitWidthScale, setScaleIfChanged]);

  const revealFile = async () => {
    if (!onRevealFile) return;
    setErrorMessage(null);
    try {
      await onRevealFile();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "文件定位失败。");
    }
  };
  const handleViewerContextMenu = (event: MouseEvent<HTMLDivElement>) => {
    if (!pdfDocument || !onCreatePageImageReference || isCreatingPageImage) return;
    const target = event.target;
    if (!(target instanceof Element) || !target.closest(".pdf-preview__page-shell")) return;
    event.preventDefault();
    event.stopPropagation();
    setPageImageMenu({ x: event.clientX, y: event.clientY });
  };

  const createCurrentPageImageReference = async () => {
    if (!pdfDocument || !onCreatePageImageReference || isCreatingPageImage) return;
    setIsCreatingPageImage(true);
    setErrorMessage(null);
    setPageImageMenu(null);
    try {
      const file = await renderPdfPageToPngFile({
        pageNumber: currentPage,
        pdfDocument,
        sourceFileName: fileName,
      });
      await onCreatePageImageReference({
        file,
        pageNumber: currentPage,
        sourceDisplayPath: displayPath,
        sourceFileName: fileName,
      });
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "引用 PDF 当前页失败。");
    } finally {
      setIsCreatingPageImage(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target instanceof HTMLButtonElement || event.target instanceof HTMLInputElement) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectPage(currentPage - 1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      selectPage(currentPage + 1);
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "=") {
      event.preventDefault();
      panZoom.zoomIn();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "-") {
      event.preventDefault();
      panZoom.zoomOut();
    }
  };

  return (
    <div className="pdf-preview" onKeyDown={handleKeyDown}>
      <div className="pdf-preview__toolbar">
        <div className="pdf-preview__meta">
          <FilePdf size={16} weight="fill" />
          <span className="pdf-preview__name">{fileName}</span>
          <span className="pdf-preview__path" title={displayPath}>{displayPath}</span>
        </div>
        <div className="pdf-preview__actions" aria-label="PDF 工具栏">
          <button
            className="pdf-preview__button"
            title={isSidebarOpen ? "隐藏缩略图" : "显示缩略图"}
            type="button"
            onClick={() => setIsSidebarOpen((isOpen) => !isOpen)}
          >
            <SidebarSimple size={15} weight="bold" />
          </button>
          <button
            className="pdf-preview__button"
            disabled={currentPage <= 1}
            title="上一页"
            type="button"
            onClick={() => selectPage(currentPage - 1)}
          >
            <CaretLeft size={15} weight="bold" />
          </button>
          <span className="pdf-preview__page-label">{currentPage} / {numPages || "-"}</span>
          <button
            className="pdf-preview__button"
            disabled={!numPages || currentPage >= numPages}
            title="下一页"
            type="button"
            onClick={() => selectPage(currentPage + 1)}
          >
            <CaretRight size={15} weight="bold" />
          </button>
          <PreviewZoomControl
            ariaLabel="PDF 预览缩放"
            disabled={!pdfDocument}
            max={maxScale}
            min={minScale}
            step={0.01}
            value={scale}
            onDecrease={() => panZoom.zoomOut()}
            onIncrease={() => panZoom.zoomIn()}
            onValueChange={(value) => panZoom.applyZoom(value)}
          />
          <button
            className="pdf-preview__button"
            title="适应宽度"
            type="button"
            onClick={() => {
              fitModeRef.current = "width";
              setFitMode("width");
              void applyFitWidth();
            }}
          >
            <FrameCorners size={15} weight="bold" />
          </button>
          <button
            className="pdf-preview__button"
            disabled={!onRevealFile}
            title="在资源管理器中打开"
            type="button"
            onClick={() => { void revealFile(); }}
          >
            <FolderOpen size={15} weight="bold" />
          </button>
        </div>
      </div>

      {errorMessage ? <div className="pdf-preview__status pdf-preview__status--error">{errorMessage}</div> : null}

      <div className="pdf-preview__body">
        {isSidebarOpen && pdfDocument && numPages > 0 ? (
          <PdfThumbnailStrip
            activePage={currentPage}
            numPages={numPages}
            pdfDocument={pdfDocument}
            onSelectPage={selectPage}
          />
        ) : null}

        <main
          className={panZoom.isPanning ? "pdf-preview__viewer pdf-preview__viewer--panning" : "pdf-preview__viewer"}
          ref={panZoom.viewportRef}
          tabIndex={0}
          onPointerCancel={panZoom.stopPan}
          onPointerDown={panZoom.startPan}
          onPointerMove={panZoom.movePan}
          onPointerUp={panZoom.stopPan}
          onContextMenu={handleViewerContextMenu}
          onWheel={panZoom.handleWheel}
        >
          {isLoadingVisible ? (
            <LoadingStrip
              ariaLabel="正在加载 PDF"
              mode="fill"
              surface="dark"
              visual="ring"
            />
          ) : pdfDocument && pdfjs ? (
            <PdfPageView
              contentRef={panZoom.contentRef}
              onPageChange={selectPage}
              pageNumber={currentPage}
              pdfDocument={pdfDocument}
              pdfjs={pdfjs}
              scale={scale}
            />
          ) : (
            <div className="pdf-preview__empty">无法显示 PDF。</div>
          )}
          {pageImageMenu ? (
            <ContextMenu
              onClose={() => setPageImageMenu(null)}
              position={pageImageMenu}
            >
              <ContextMenuItem
                disabled={isCreatingPageImage}
                onSelect={() => { void createCurrentPageImageReference(); }}
              >
                引用当前页到对话
              </ContextMenuItem>
            </ContextMenu>
          ) : null}
        </main>
      </div>
    </div>
  );
}

function isPdfMissingError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return /\b404\b/.test(error.message);
}

function clampScale(value: number) {
  return Math.max(minScale, Math.min(maxScale, Math.round(value * 100) / 100));
}

function shouldStartPdfPan(event: PointerEvent<HTMLDivElement>) {
  const target = event.target;
  if (!(target instanceof Element)) return true;

  return !target.closest(
    "a, button, input, textarea, select, .pdf-preview__text-layer span, .pdf-preview__annotation-layer section",
  );
}
