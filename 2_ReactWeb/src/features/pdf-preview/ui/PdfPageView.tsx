import { useEffect, useRef, useState, type RefObject } from "react";

import type {
  PdfDocumentProxy,
  PdfJsLib,
} from "../model/pdfjsLoader";
import {
  createPdfDownloadManager,
  createPdfLinkService,
} from "../model/pdfLinkAdapter";
import { resolvePdfCanvasOutputScale } from "../model/pdfCanvasScale";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";

type PdfPageViewProps = {
  contentRef: RefObject<HTMLDivElement | null>;
  onPageChange: (pageNumber: number) => void;
  pageNumber: number;
  pdfDocument: PdfDocumentProxy;
  pdfjs: PdfJsLib;
  scale: number;
};

type TextLayerInstance = {
  cancel: () => void;
  render: () => Promise<unknown>;
};

export function PdfPageView({
  contentRef,
  onPageChange,
  pageNumber,
  pdfDocument,
  pdfjs,
  scale,
}: PdfPageViewProps) {
  const annotationLayerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const renderedPageRef = useRef<{ pageNumber: number; pdfDocument: PdfDocumentProxy } | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  const [annotationError, setAnnotationError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const isPageLoadingVisible = useMinimumLoading(isPageLoading);

  useEffect(() => {
    let isCancelled = false;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;
    let textLayer: TextLayerInstance | null = null;

    const renderPage = async () => {
      const annotationLayerElement = annotationLayerRef.current;
      const visibleCanvas = canvasRef.current;
      const textLayerElement = textLayerRef.current;
      if (!annotationLayerElement || !visibleCanvas || !textLayerElement) return;

      const shouldShowPageLoading = renderedPageRef.current?.pdfDocument !== pdfDocument
        || renderedPageRef.current.pageNumber !== pageNumber;
      setIsPageLoading(shouldShowPageLoading);
      setAnnotationError(null);
      setRenderError(null);

      try {
        const page = await pdfDocument.getPage(pageNumber);
        if (isCancelled) return;

        const viewport = page.getViewport({ scale });
        const outputScale = resolvePdfCanvasOutputScale(viewport);
        const renderCanvas = document.createElement("canvas");
        renderCanvas.width = Math.floor(viewport.width * outputScale);
        renderCanvas.height = Math.floor(viewport.height * outputScale);

        renderTask = page.render({
          annotationMode: pdfjs.AnnotationMode.ENABLE_FORMS,
          canvas: renderCanvas,
          transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined,
          viewport,
        });
        await renderTask.promise;
        if (isCancelled) return;

        visibleCanvas.width = renderCanvas.width;
        visibleCanvas.height = renderCanvas.height;
        visibleCanvas.style.width = `${viewport.width}px`;
        visibleCanvas.style.height = `${viewport.height}px`;
        const visibleCanvasContext = visibleCanvas.getContext("2d");
        if (!visibleCanvasContext) {
          throw new Error("PDF 页面画布不可用。");
        }
        visibleCanvasContext.drawImage(renderCanvas, 0, 0);
        renderCanvas.width = 0;
        renderCanvas.height = 0;
        annotationLayerElement.replaceChildren();
        textLayerElement.replaceChildren();
        textLayerElement.style.width = `${viewport.width}px`;
        textLayerElement.style.height = `${viewport.height}px`;

        textLayer = new pdfjs.TextLayer({
          container: textLayerElement,
          textContentSource: page.streamTextContent({ includeMarkedContent: true }),
          viewport,
        }) as TextLayerInstance;
        await textLayer.render();
        if (isCancelled) return;

        const linkService = createPdfLinkService({
          currentPageNumber: pageNumber,
          onPageChange,
          pdfDocument,
        });
        const annotationViewport = viewport.clone({ dontFlip: true });
        const annotationLayer = new pdfjs.AnnotationLayer({
          accessibilityManager: null,
          annotationCanvasMap: null,
          annotationEditorUIManager: null,
          annotationStorage: pdfDocument.annotationStorage,
          commentManager: null,
          div: annotationLayerElement,
          linkService,
          page,
          structTreeLayer: null,
          viewport: annotationViewport,
        });
        const [annotations, fieldObjects, optionalContentConfig] = await Promise.all([
          page.getAnnotations({ intent: "display" }),
          pdfDocument.getFieldObjects(),
          pdfDocument.getOptionalContentConfig({ intent: "display" }),
        ]);
        if (isCancelled) return;

        try {
          await annotationLayer.render({
            annotations,
            annotationStorage: pdfDocument.annotationStorage,
            div: annotationLayerElement,
            downloadManager: createPdfDownloadManager() as never,
            enableScripting: false,
            fieldObjects,
            hasJSActions: false,
            imageResourcesPath: "",
            linkService: linkService as never,
            optionalContentConfig,
            page,
            renderForms: true,
            viewport: annotationViewport,
          });
        } catch (err) {
          if (!isCancelled) {
            setAnnotationError(err instanceof Error ? err.message : "PDF 批注/表单层渲染失败。");
          }
        }

        if (!isCancelled) {
          renderedPageRef.current = { pageNumber, pdfDocument };
          setIsPageLoading(false);
        }
      } catch (err) {
        if (isCancelled) return;
        setIsPageLoading(false);
        setRenderError(err instanceof Error ? err.message : "PDF 页面渲染失败。");
      }
    };

    void renderPage();

    return () => {
      isCancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
    };
  }, [onPageChange, pageNumber, pdfDocument, pdfjs, scale]);

  return (
    <div className="pdf-preview__page-shell">
      {isPageLoadingVisible ? (
        <LoadingStrip
          ariaLabel="正在渲染 PDF 页面"
          className="pdf-preview__page-loading"
          mode="fill"
          surface="dark"
          visual="ring"
        />
      ) : null}
      {!isPageLoadingVisible && renderError ? <div className="pdf-preview__page-error">{renderError}</div> : null}
      {!isPageLoadingVisible && annotationError ? (
        <div className="pdf-preview__page-warning">批注/表单层渲染失败，正文仍可查看。</div>
      ) : null}
      <div
        className={isPageLoadingVisible
          ? "pdf-preview__page pdf-preview__page--loading-hidden"
          : "pdf-preview__page"}
        ref={contentRef}
      >
        <canvas className="pdf-preview__canvas" ref={canvasRef} />
        <div className="textLayer pdf-preview__text-layer" ref={textLayerRef} />
        <div className="annotationLayer pdf-preview__annotation-layer" ref={annotationLayerRef} />
      </div>
    </div>
  );
}
