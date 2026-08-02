import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { resolvePdfCanvasOutputScale } from "../model/pdfCanvasScale";
import type { PdfDocumentProxy } from "../model/pdfjsLoader";

type PdfThumbnailStripProps = {
  activePage: number;
  numPages: number;
  onSelectPage: (pageNumber: number) => void;
  pdfDocument: PdfDocumentProxy;
};

export function PdfThumbnailStrip({
  activePage,
  numPages,
  onSelectPage,
  pdfDocument,
}: PdfThumbnailStripProps) {
  const stripRef = useRef<HTMLElement | null>(null);
  const pageNumbers = useMemo(
    () => Array.from({ length: numPages }, (_, index) => index + 1),
    [numPages],
  );

  return (
    <aside className="pdf-preview__thumbnails" aria-label="PDF 缩略图" ref={stripRef}>
      {pageNumbers.map((pageNumber) => (
        <PdfThumbnail
          active={pageNumber === activePage}
          key={pageNumber}
          pageNumber={pageNumber}
          pdfDocument={pdfDocument}
          scrollRootRef={stripRef}
          onSelect={() => onSelectPage(pageNumber)}
        />
      ))}
    </aside>
  );
}

function PdfThumbnail({
  active,
  onSelect,
  pageNumber,
  pdfDocument,
  scrollRootRef,
}: {
  active: boolean;
  onSelect: () => void;
  pageNumber: number;
  pdfDocument: PdfDocumentProxy;
  scrollRootRef: RefObject<HTMLElement | null>;
}) {
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);
  const [shouldRender, setShouldRender] = useState(active);

  useEffect(() => {
    if (active) {
      setShouldRender(true);
    }
  }, [active]);

  useEffect(() => {
    if (shouldRender) return undefined;

    const root = scrollRootRef.current;
    const target = buttonRef.current;
    if (!root || !target) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShouldRender(true);
          observer.disconnect();
        }
      },
      {
        root,
        rootMargin: "360px 0px",
        threshold: 0.01,
      },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [scrollRootRef, shouldRender]);

  useEffect(() => {
    if (!shouldRender) return undefined;

    let isCancelled = false;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;

    const renderThumbnail = async () => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      setFailed(false);
      try {
        const page = await pdfDocument.getPage(pageNumber);
        if (isCancelled) return;

        const baseViewport = page.getViewport({ scale: 1 });
        const scale = 92 / baseViewport.width;
        const viewport = page.getViewport({ scale });
        const outputScale = resolvePdfCanvasOutputScale(viewport, {
          maxCanvasPixels: 1_000_000,
        });
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        renderTask = page.render({
          canvas,
          transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined,
          viewport,
        });
        await renderTask.promise;
      } catch {
        if (!isCancelled) {
          setFailed(true);
        }
      }
    };

    void renderThumbnail();

    return () => {
      isCancelled = true;
      renderTask?.cancel();
    };
  }, [pageNumber, pdfDocument, shouldRender]);

  return (
    <button
      className={active ? "pdf-preview__thumbnail pdf-preview__thumbnail--active" : "pdf-preview__thumbnail"}
      ref={buttonRef}
      type="button"
      onClick={onSelect}
    >
      <span className="pdf-preview__thumbnail-canvas-wrap">
        <span className="pdf-preview__thumbnail-label">{pageNumber}</span>
        {failed ? <span className="pdf-preview__thumbnail-error">失败</span> : null}
        {!failed && shouldRender ? <canvas ref={canvasRef} /> : null}
        {!failed && !shouldRender ? <span className="pdf-preview__thumbnail-placeholder" /> : null}
      </span>
    </button>
  );
}
