import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from "react";
import {
  CaretLeft,
  CaretRight,
} from "@phosphor-icons/react";

import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type {
  LoadState,
  OfficeLoadingVisibilityChange,
  PPTXViewerWithDimensions,
  PresentationSlideImageReferencePayload,
  PresentationZoomAnchor,
  SlideDimensions,
} from "./officePreviewTypes";
import { officePreviewMinimumLoadingMs } from "./officePreviewTypes";
import { clampOfficeZoom } from "./officePreviewUtils";
import {
  buildPresentationSlideImageFileName,
  canvasToPngBlob,
  preparePresentationCanvas,
  presentationThumbnailZoom,
  presentationZoomStep,
  readPresentationDimensions,
  repairPresentationCanvasBlankBottomEdge,
  resolvePresentationDimensions,
  resolvePresentationZoomAnchor,
  restorePresentationZoomAnchor,
  slideCssSize,
} from "./presentationPreviewUtils";

type PresentationPreviewProps = {
  displayPath: string;
  fileName: string;
  onCreateSlideImageReference?: ((payload: PresentationSlideImageReferencePayload) => Promise<void>) | null;
  onLoadingVisibleChange?: OfficeLoadingVisibilityChange;
  onMissing?: (() => void) | null;
  src: string | null;
  zoom: number;
  onZoomChange: (zoom: number) => void;
};

export function PresentationPreview({
  displayPath,
  fileName,
  onCreateSlideImageReference,
  onLoadingVisibleChange,
  onMissing = null,
  src,
  zoom,
  onZoomChange,
}: PresentationPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const didApplyInitialZoomRef = useRef(false);
  const onMissingRef = useRef(onMissing);
  const dragStateRef = useRef<{
    pointerId: number;
    scrollLeft: number;
    scrollTop: number;
    x: number;
    y: number;
  } | null>(null);
  const pendingZoomAnchorRef = useRef<PresentationZoomAnchor | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const slideDimensionsRef = useRef<SlideDimensions | null>(null);
  const thumbnailButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const thumbnailCanvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const thumbnailRenderedIndexesRef = useRef<Set<number>>(new Set());
  const thumbnailRenderRunIdRef = useRef(0);
  const thumbnailStripRef = useRef<HTMLDivElement | null>(null);
  const slideRenderRunIdRef = useRef(0);
  const viewerRef = useRef<PPTXViewerWithDimensions | null>(null);
  const zoomRef = useRef(zoom);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [slideReferenceMenu, setSlideReferenceMenu] = useState<{ x: number; y: number } | null>(null);
  const [slideDimensions, setSlideDimensions] = useState<SlideDimensions | null>(null);
  const [slideCount, setSlideCount] = useState(0);
  const [state, setState] = useState<LoadState>(() => (src ? "loading" : "idle"));
  const [visibleThumbnailIndexes, setVisibleThumbnailIndexes] = useState<Set<number>>(() => new Set());
  const isLoadingVisible = useMinimumLoading(state === "loading", officePreviewMinimumLoadingMs);

  useEffect(() => {
    onMissingRef.current = onMissing;
  }, [onMissing]);

  useEffect(() => {
    onLoadingVisibleChange?.(isLoadingVisible);
  }, [isLoadingVisible, onLoadingVisibleChange]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  const renderSlide = useCallback(async (slideIndex: number, nextZoom: number) => {
    const viewer = viewerRef.current;
    const visibleCanvas = canvasRef.current;
    if (!viewer || !visibleCanvas) return false;

    const runId = slideRenderRunIdRef.current + 1;
    slideRenderRunIdRef.current = runId;
    const renderCanvas = document.createElement("canvas");
    preparePresentationCanvas(
      renderCanvas,
      slideDimensionsRef.current ?? resolvePresentationDimensions(viewer),
      nextZoom,
    );

    try {
      await viewer.render(renderCanvas, {
        quality: "high",
        slideIndex,
      });
    } catch (err) {
      if (slideRenderRunIdRef.current !== runId) return false;
      throw err;
    }

    if (
      slideRenderRunIdRef.current !== runId
      || viewerRef.current !== viewer
      || canvasRef.current !== visibleCanvas
    ) {
      return false;
    }

    repairPresentationCanvasBlankBottomEdge(renderCanvas);
    copyPresentationCanvas(renderCanvas, visibleCanvas);
    restorePresentationZoomAnchor(scrollRef.current, visibleCanvas, pendingZoomAnchorRef);
    return true;
  }, []);

  useEffect(() => {
    if (!src) {
      setState("idle");
      setErrorMessage(null);
      setSlideDimensions(null);
      slideDimensionsRef.current = null;
      setSlideCount(0);
      setCurrentSlide(0);
      setSlideReferenceMenu(null);
      thumbnailButtonRefs.current = [];
      thumbnailCanvasRefs.current = [];
      thumbnailRenderedIndexesRef.current = new Set();
      thumbnailRenderRunIdRef.current += 1;
      slideRenderRunIdRef.current += 1;
      setVisibleThumbnailIndexes(new Set());
      didApplyInitialZoomRef.current = false;
      return undefined;
    }

    let isCancelled = false;
    const controller = new AbortController();

    const load = async () => {
      setState("loading");
      setErrorMessage(null);
      setSlideDimensions(null);
      slideDimensionsRef.current = null;
      setSlideCount(0);
      setCurrentSlide(0);
      setSlideReferenceMenu(null);
      thumbnailButtonRefs.current = [];
      thumbnailCanvasRefs.current = [];
      thumbnailRenderedIndexesRef.current = new Set();
      thumbnailRenderRunIdRef.current += 1;
      slideRenderRunIdRef.current += 1;
      setVisibleThumbnailIndexes(new Set());
      didApplyInitialZoomRef.current = false;

      let viewer: PPTXViewerWithDimensions | null = null;

      try {
        const [{ PPTXViewer }, response] = await Promise.all([
          import("pptxviewjs"),
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
        viewer = new PPTXViewer({
          autoChartRerenderDelayMs: 0,
          backgroundColor: "#ffffff",
          canvas: canvasRef.current,
          enableThumbnails: false,
        });
        viewerRef.current = viewer;
        const arrayBuffer = await response.arrayBuffer();
        if (isCancelled) return;
        const dimensions = await readPresentationDimensions(arrayBuffer) ?? resolvePresentationDimensions(viewer);
        slideDimensionsRef.current = dimensions;
        await viewer.loadFile(arrayBuffer);
        if (isCancelled) return;
        const count = viewer.getSlideCount();
        setSlideDimensions(dimensions);
        setSlideCount(count);
        const didRender = await renderSlide(0, zoomRef.current);
        if (isCancelled) return;
        if (!didRender) return;
        setState("ready");
      } catch (err) {
        if (isCancelled || controller.signal.aborted) return;
        setState("error");
        setErrorMessage(err instanceof Error ? err.message : "PPT 文件预览失败。");
        viewer?.destroy();
        if (viewerRef.current === viewer) {
          viewerRef.current = null;
        }
      }
    };

    void load();

    return () => {
      isCancelled = true;
      controller.abort();
      slideRenderRunIdRef.current += 1;
      const viewer = viewerRef.current;
      viewer?.destroy();
      if (viewerRef.current === viewer) {
        viewerRef.current = null;
      }
    };
  }, [renderSlide, src]);

  useEffect(() => {
    if (state !== "ready" || !slideDimensions || !scrollRef.current) return undefined;

    const applyInitialZoom = () => {
      if (didApplyInitialZoomRef.current) return;
      const viewportWidth = scrollRef.current?.clientWidth ?? 0;
      if (viewportWidth <= 0) return;
      const baseWidth = slideCssSize(slideDimensions).width;
      const nextZoom = clampOfficeZoom((viewportWidth - 96) / baseWidth);
      didApplyInitialZoomRef.current = true;
      zoomRef.current = nextZoom;
      onZoomChange(nextZoom);
    };

    applyInitialZoom();
    const observer = new ResizeObserver(applyInitialZoom);
    observer.observe(scrollRef.current);
    return () => observer.disconnect();
  }, [onZoomChange, slideDimensions, state]);

  useEffect(() => {
    if (state !== "ready") return;
    void renderSlide(currentSlide, zoom).catch((err: unknown) => {
      setErrorMessage(err instanceof Error ? err.message : "PPT 页面渲染失败。");
    });
  }, [currentSlide, renderSlide, state, zoom]);

  useEffect(() => {
    if (state !== "ready" || slideCount <= 0) return undefined;

    setVisibleThumbnailIndexes((current) => {
      if (current.has(currentSlide)) return current;
      const next = new Set(current);
      next.add(currentSlide);
      return next;
    });
  }, [currentSlide, slideCount, state]);

  useEffect(() => {
    if (state !== "ready" || slideCount <= 0) return undefined;

    const root = thumbnailStripRef.current;
    if (!root) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        const nextIndexes = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => Number((entry.target as HTMLElement).dataset.slideIndex))
          .filter((slideIndex) => Number.isInteger(slideIndex));
        if (nextIndexes.length === 0) return;

        setVisibleThumbnailIndexes((current) => {
          let changed = false;
          const next = new Set(current);
          for (const slideIndex of nextIndexes) {
            if (!next.has(slideIndex)) {
              next.add(slideIndex);
              changed = true;
            }
          }
          return changed ? next : current;
        });
      },
      {
        root,
        rootMargin: "0px 360px",
        threshold: 0.01,
      },
    );

    for (let slideIndex = 0; slideIndex < slideCount; slideIndex += 1) {
      const button = thumbnailButtonRefs.current[slideIndex];
      if (button) {
        observer.observe(button);
      }
    }

    return () => observer.disconnect();
  }, [slideCount, state]);

  useEffect(() => {
    if (state !== "ready" || !slideDimensions || slideCount <= 0 || visibleThumbnailIndexes.size === 0) {
      return undefined;
    }

    let isCancelled = false;
    const runId = thumbnailRenderRunIdRef.current + 1;
    thumbnailRenderRunIdRef.current = runId;

    const renderThumbnails = async () => {
      const viewer = viewerRef.current;
      if (!viewer) return;
      const indexes = Array.from(visibleThumbnailIndexes)
        .filter((slideIndex) => slideIndex >= 0 && slideIndex < slideCount && !thumbnailRenderedIndexesRef.current.has(slideIndex))
        .sort((left, right) => Math.abs(left - currentSlide) - Math.abs(right - currentSlide));

      for (const slideIndex of indexes) {
        if (isCancelled || thumbnailRenderRunIdRef.current !== runId) return;
        const canvas = thumbnailCanvasRefs.current[slideIndex];
        if (!canvas) continue;
        preparePresentationCanvas(canvas, slideDimensions, presentationThumbnailZoom(slideDimensions));
        await viewer.render(canvas, {
          quality: "high",
          slideIndex,
        });
        repairPresentationCanvasBlankBottomEdge(canvas);
        thumbnailRenderedIndexesRef.current.add(slideIndex);
      }
    };

    void renderThumbnails().catch(() => undefined);

    return () => {
      isCancelled = true;
    };
  }, [currentSlide, slideCount, slideDimensions, state, visibleThumbnailIndexes]);

  useEffect(() => {
    thumbnailButtonRefs.current[currentSlide]?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [currentSlide]);

  const goToSlide = useCallback((slideIndex: number) => {
    setCurrentSlide(Math.max(0, Math.min(slideCount - 1, slideIndex)));
  }, [slideCount]);

  const handlePresentationWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    if (state !== "ready") return;

    event.preventDefault();
    pendingZoomAnchorRef.current = resolvePresentationZoomAnchor(
      scrollRef.current,
      canvasRef.current,
      event,
    );

    const direction = event.deltaY < 0 ? 1 : -1;
    const nextZoom = clampOfficeZoom(zoomRef.current + direction * presentationZoomStep(zoomRef.current));
    zoomRef.current = nextZoom;
    onZoomChange(nextZoom);
  }, [onZoomChange, state]);

  const startDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const scroll = scrollRef.current;
    if (!scroll || event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest("button")) return;

    dragStateRef.current = {
      pointerId: event.pointerId,
      scrollLeft: scroll.scrollLeft,
      scrollTop: scroll.scrollTop,
      x: event.clientX,
      y: event.clientY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);
  }, []);

  const moveDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    const scroll = scrollRef.current;
    if (!drag || !scroll || drag.pointerId !== event.pointerId) return;

    event.preventDefault();
    scroll.scrollLeft = drag.scrollLeft - (event.clientX - drag.x);
    scroll.scrollTop = drag.scrollTop - (event.clientY - drag.y);
  }, []);

  const stopDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    dragStateRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsDragging(false);
  }, []);

  const handlePresentationContextMenu = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (state !== "ready" || !onCreateSlideImageReference) return;
    event.preventDefault();
    event.stopPropagation();
    setSlideReferenceMenu({ x: event.clientX, y: event.clientY });
  }, [onCreateSlideImageReference, state]);

  const createSlideImageReference = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || canvas.width <= 0 || canvas.height <= 0 || !onCreateSlideImageReference) {
      setErrorMessage("当前 PPT 页面尚未渲染完成。");
      setSlideReferenceMenu(null);
      return;
    }

    const slideNumber = currentSlide + 1;
    setSlideReferenceMenu(null);
    void canvasToPngBlob(canvas)
      .then((blob) => onCreateSlideImageReference({
        file: new File([blob], buildPresentationSlideImageFileName(fileName, slideNumber), {
          type: "image/png",
        }),
        slideNumber,
        sourceDisplayPath: displayPath,
        sourceFileName: fileName,
      }))
      .then(() => {
        setErrorMessage(null);
      })
      .catch((err: unknown) => {
        setErrorMessage(err instanceof Error ? err.message : "引用 PPT 当前页失败。");
      });
  }, [currentSlide, displayPath, fileName, onCreateSlideImageReference]);

  return (
    <main className="office-preview__body">
      <div className="office-preview__presentation-bar">
        <button
          className="office-preview__button"
          disabled={currentSlide <= 0}
          title="上一页"
          type="button"
          onClick={() => goToSlide(currentSlide - 1)}
        >
          <CaretLeft size={15} weight="bold" />
        </button>
        <span>{slideCount > 0 ? `${currentSlide + 1} / ${slideCount}` : "- / -"}</span>
        <button
          className="office-preview__button"
          disabled={!slideCount || currentSlide >= slideCount - 1}
          title="下一页"
          type="button"
          onClick={() => goToSlide(currentSlide + 1)}
        >
          <CaretRight size={15} weight="bold" />
        </button>
      </div>
      {isLoadingVisible ? (
        <LoadingStrip
          ariaLabel="正在加载 PPT 演示文稿"
          mode="fill"
          surface="dark"
          visual="ring"
        />
      ) : null}
      {!isLoadingVisible && state === "error" ? (
        <div className="office-preview__status office-preview__status--error">{errorMessage}</div>
      ) : null}
      {!isLoadingVisible && state === "ready" && errorMessage ? (
        <div className="office-preview__status office-preview__status--error">{errorMessage}</div>
      ) : null}
      <div
        className={isLoadingVisible
          ? "office-preview__presentation-shell office-preview__presentation-shell--loading-hidden"
          : "office-preview__presentation-shell"}
      >
        <button
          className="office-preview__presentation-nav office-preview__presentation-nav--prev"
          disabled={currentSlide <= 0}
          title="上一页"
          type="button"
          onClick={() => goToSlide(currentSlide - 1)}
        >
          <CaretLeft size={22} weight="bold" />
        </button>
        <div
          className={isDragging
            ? "office-preview__scroll office-preview__scroll--presentation office-preview__scroll--dragging"
            : "office-preview__scroll office-preview__scroll--presentation"}
          ref={scrollRef}
          onPointerCancel={stopDrag}
          onPointerDown={startDrag}
          onPointerLeave={stopDrag}
          onPointerMove={moveDrag}
          onPointerUp={stopDrag}
          onContextMenu={handlePresentationContextMenu}
          onWheel={handlePresentationWheel}
        >
          <div className="office-preview__presentation-stage">
            <canvas className="office-preview__presentation-canvas" ref={canvasRef} />
          </div>
        </div>
        <button
          className="office-preview__presentation-nav office-preview__presentation-nav--next"
          disabled={!slideCount || currentSlide >= slideCount - 1}
          title="下一页"
          type="button"
          onClick={() => goToSlide(currentSlide + 1)}
        >
          <CaretRight size={22} weight="bold" />
        </button>
      </div>
      {slideReferenceMenu ? (
        <ContextMenu
          onClose={() => setSlideReferenceMenu(null)}
          position={{ x: slideReferenceMenu.x, y: slideReferenceMenu.y }}
        >
          <ContextMenuItem onSelect={createSlideImageReference}>
            引用当前页到对话
          </ContextMenuItem>
        </ContextMenu>
      ) : null}
      {state === "ready" && slideCount > 1 ? (
        <div className="office-preview__presentation-thumbnails" aria-label="PPT 缩略图" ref={thumbnailStripRef}>
          {Array.from({ length: slideCount }, (_, slideIndex) => (
            <button
              className={slideIndex === currentSlide
                ? "office-preview__presentation-thumbnail office-preview__presentation-thumbnail--active"
                : "office-preview__presentation-thumbnail"}
              data-slide-index={slideIndex}
              key={slideIndex}
              title={`第 ${slideIndex + 1} 页`}
              type="button"
              ref={(node) => {
                thumbnailButtonRefs.current[slideIndex] = node;
              }}
              onClick={() => goToSlide(slideIndex)}
            >
              <span className="office-preview__presentation-thumbnail-number">{slideIndex + 1}</span>
              {visibleThumbnailIndexes.has(slideIndex) ? (
                <canvas
                  ref={(node) => {
                    thumbnailCanvasRefs.current[slideIndex] = node;
                  }}
                />
              ) : (
                <span className="office-preview__presentation-thumbnail-placeholder" />
              )}
            </button>
          ))}
        </div>
      ) : null}
      {state === "idle" ? <div className="office-preview__empty">PPT 文件地址无效。</div> : null}
    </main>
  );
}

function copyPresentationCanvas(source: HTMLCanvasElement, target: HTMLCanvasElement) {
  target.width = source.width;
  target.height = source.height;
  target.style.width = source.style.width;
  target.style.height = source.style.height;

  const context = target.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, target.width, target.height);
  context.drawImage(source, 0, 0);
}
