import { useEffect, useRef, useState, type MouseEvent, type PointerEvent, type WheelEvent } from "react";
import {
  ArrowsOutSimple,
  FrameCorners,
  ImageBroken,
} from "@phosphor-icons/react";

import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { PreviewZoomControl } from "../../../shared/ui/preview-zoom-control";
import "./image-preview.css";

type ImagePreviewProps = {
  displayPath: string;
  fileName: string;
  onReferenceImage?: (() => void) | null;
  src: string | null;
};

type NaturalSize = {
  height: number;
  width: number;
};

type LoadedImage = NaturalSize & {
  src: string;
};

type ViewportSize = {
  height: number;
  width: number;
};

type ReferenceMenuState = {
  x: number;
  y: number;
} | null;

const minZoom = 0.1;
const maxZoom = 8;

export function ImagePreview({
  displayPath,
  fileName,
  onReferenceImage = null,
  src,
}: ImagePreviewProps) {
  const panStartRef = useRef<{
    offsetX: number;
    offsetY: number;
    pointerId: number;
    startX: number;
    startY: number;
  } | null>(null);
  const [fitToView, setFitToView] = useState(true);
  const [isPanning, setIsPanning] = useState(false);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [loadedImage, setLoadedImage] = useState<LoadedImage | null>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [referenceMenu, setReferenceMenu] = useState<ReferenceMenuState>(null);
  const [viewportSize, setViewportSize] = useState<ViewportSize>({ height: 0, width: 0 });
  const [zoom, setZoom] = useState(1);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const loadRequestRef = useRef(0);

  const isLoadingVisible = useMinimumLoading(loadState === "loading", 180);
  const canShowImage = loadState === "ready" && loadedImage !== null && !isLoadingVisible;
  const fitZoom = getFitZoom(viewportSize, loadedImage);
  const zoomLabel = fitToView ? "适应" : `${Math.round(zoom * 100)}%`;
  const resolvedZoom = fitToView ? fitZoom : zoom;
  const imageOffset = fitToView ? { x: 0, y: 0 } : offset;
  const imageStyle = {
    height: loadedImage ? `${Math.max(1, Math.round(loadedImage.height))}px` : undefined,
    transform: `translate(${Math.round(imageOffset.x)}px, ${Math.round(imageOffset.y)}px) scale(${resolvedZoom})`,
    width: loadedImage ? `${Math.max(1, Math.round(loadedImage.width))}px` : undefined,
  };

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;

    const updateViewportSize = () => {
      setViewportSize({
        height: viewport.clientHeight,
        width: viewport.clientWidth,
      });
    };
    updateViewportSize();

    if (typeof ResizeObserver === "undefined") {
      return undefined;
    }

    const observer = new ResizeObserver(updateViewportSize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  const resetPan = () => {
    panStartRef.current = null;
    setIsPanning(false);
    setOffset({ x: 0, y: 0 });
  };

  const resetToFit = () => {
    resetPan();
    setFitToView(true);
    setZoom(1);
  };

  useEffect(() => {
    const viewport = viewportRef.current;
    const pointerId = panStartRef.current?.pointerId;
    if (viewport && pointerId !== undefined && viewport.hasPointerCapture(pointerId)) {
      viewport.releasePointerCapture(pointerId);
    }
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    panStartRef.current = null;
    setFitToView(true);
    setIsPanning(false);
    setLoadedImage(null);
    setOffset({ x: 0, y: 0 });
    setReferenceMenu(null);
    setZoom(1);

    if (!src) {
      setLoadState("error");
      return undefined;
    }

    setLoadState("loading");
    const image = new window.Image();
    image.decoding = "async";
    image.onload = () => {
      if (loadRequestRef.current !== requestId) return;
      setLoadedImage({
        height: image.naturalHeight,
        src,
        width: image.naturalWidth,
      });
      setLoadState("ready");
    };
    image.onerror = () => {
      if (loadRequestRef.current !== requestId) return;
      setLoadedImage(null);
      setLoadState("error");
    };
    image.src = src;

    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [displayPath, src]);

  const showActualSize = () => {
    resetPan();
    setFitToView(false);
    setZoom(1);
  };

  const zoomBy = (direction: -1 | 1) => {
    if (!canShowImage || !loadedImage) return;
    setFitToView(false);
    setZoom((currentZoom) => {
      const current = fitToView ? fitZoom : currentZoom;
      return clampZoom(current + direction * getZoomStep(current));
    });
  };

  const startPan = (event: PointerEvent<HTMLDivElement>) => {
    if (!canShowImage || fitToView || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panStartRef.current = {
      offsetX: offset.x,
      offsetY: offset.y,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    };
    setIsPanning(true);
  };

  const movePan = (event: PointerEvent<HTMLDivElement>) => {
    const start = panStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.preventDefault();
    setOffset({
      x: start.offsetX + event.clientX - start.startX,
      y: start.offsetY + event.clientY - start.startY,
    });
  };

  const stopPan = (event: PointerEvent<HTMLDivElement>) => {
    const start = panStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panStartRef.current = null;
    setIsPanning(false);
  };

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!canShowImage || !loadedImage) return;
    event.preventDefault();
    zoomBy(event.deltaY < 0 ? 1 : -1);
  };

  const setCustomZoom = (value: number) => {
    if (!canShowImage || !loadedImage) return;
    setFitToView(false);
    setZoom(clampZoom(value));
  };

  const handleContextMenu = (event: MouseEvent<HTMLElement>) => {
    if (!onReferenceImage || !canShowImage) return;
    event.preventDefault();
    event.stopPropagation();
    setReferenceMenu({ x: event.clientX, y: event.clientY });
  };

  return (
    <div className="image-preview">
      <div className="image-preview__toolbar">
        <div className="image-preview__meta">
          <span className="image-preview__name">{fileName}</span>
          <span className="image-preview__path" title={displayPath}>{displayPath}</span>
        </div>
        <div className="image-preview__actions" aria-label="图片预览工具">
          <PreviewZoomControl
            ariaLabel="图片预览缩放"
            disabled={!canShowImage}
            max={maxZoom}
            min={minZoom}
            step={0.01}
            value={resolvedZoom}
            valueLabel={zoomLabel}
            onDecrease={() => zoomBy(-1)}
            onIncrease={() => zoomBy(1)}
            onValueChange={setCustomZoom}
          />
          <button
            className="image-preview__button"
            title="适应窗口"
            type="button"
            onClick={resetToFit}
          >
            <FrameCorners size={15} weight="bold" />
          </button>
          <button
            className="image-preview__button"
            title="原始大小"
            type="button"
            onClick={showActualSize}
          >
            <ArrowsOutSimple size={15} weight="bold" />
          </button>
        </div>
      </div>
      <div
        className={isPanning ? "image-preview__viewport image-preview__viewport--panning" : "image-preview__viewport"}
        ref={viewportRef}
        onLostPointerCapture={stopPan}
        onPointerCancel={stopPan}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={stopPan}
        onContextMenu={handleContextMenu}
        onWheel={handleWheel}
      >
        {canShowImage && loadedImage ? (
          <div className="image-preview__stage">
            <img
              key={loadedImage.src}
              alt={fileName}
              className="image-preview__image"
              draggable={false}
              src={loadedImage.src}
              style={imageStyle}
            />
          </div>
        ) : loadState === "error" ? (
          <div className="image-preview__error" role="status">
            <ImageBroken size={28} weight="duotone" />
            <span>图片无法预览</span>
          </div>
        ) : (
          <LoadingStrip
            ariaLabel="正在加载图片"
            className="image-preview__loading"
            mode="fill"
            surface="dark"
            visual="ring"
          />
        )}
      </div>
      {referenceMenu ? (
        <ContextMenu
          onClose={() => setReferenceMenu(null)}
          position={{ x: referenceMenu.x, y: referenceMenu.y }}
        >
          <ContextMenuItem
            onSelect={() => {
              onReferenceImage?.();
              setReferenceMenu(null);
            }}
          >
            引用到对话
          </ContextMenuItem>
        </ContextMenu>
      ) : null}
    </div>
  );
}

function clampZoom(value: number) {
  return Math.max(minZoom, Math.min(maxZoom, Math.round(value * 100) / 100));
}

function getFitZoom(viewportSize: ViewportSize, naturalSize: NaturalSize | null) {
  if (
    !naturalSize
    || naturalSize.width <= 0
    || naturalSize.height <= 0
    || viewportSize.width <= 0
    || viewportSize.height <= 0
  ) {
    return 1;
  }

  const stagePadding = 36;
  const maxWidth = Math.max(1, viewportSize.width - stagePadding);
  const maxHeight = Math.max(1, viewportSize.height - stagePadding);
  return clampZoom(Math.min(1, maxWidth / naturalSize.width, maxHeight / naturalSize.height));
}

function getZoomStep(currentZoom: number) {
  if (currentZoom < 0.5) return 0.1;
  if (currentZoom < 2) return 0.25;
  return 0.5;
}
