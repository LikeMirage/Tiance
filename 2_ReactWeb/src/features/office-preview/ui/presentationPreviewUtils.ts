import type { WheelEvent } from "react";

import type {
  PPTXViewerWithDimensions,
  PresentationZoomAnchor,
  SlideDimensions,
} from "./officePreviewTypes";

export function resolvePresentationDimensions(viewer: PPTXViewerWithDimensions): SlideDimensions {
  const dimensions = viewer.getSlideDimensions?.();
  if (
    dimensions
    && Number.isFinite(dimensions.cx)
    && Number.isFinite(dimensions.cy)
    && dimensions.cx > 0
    && dimensions.cy > 0
  ) {
    return dimensions;
  }
  return { cx: 9144000, cy: 6858000 };
}

export function slideCssSize(dimensions: SlideDimensions) {
  return {
    height: Math.max(1, (dimensions.cy / 914400) * 96),
    width: Math.max(1, (dimensions.cx / 914400) * 96),
  };
}

export function preparePresentationCanvas(
  canvas: HTMLCanvasElement,
  dimensions: SlideDimensions,
  zoom: number,
) {
  const baseSize = slideCssSize(dimensions);
  const width = Math.max(1, Math.round(baseSize.width * zoom));
  const height = Math.max(1, Math.round(baseSize.height * zoom));
  canvas.width = width;
  canvas.height = height;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
}

export function resolvePresentationZoomAnchor(
  viewport: HTMLElement | null,
  content: HTMLElement | null,
  event: WheelEvent<HTMLDivElement>,
): PresentationZoomAnchor | null {
  if (!viewport || !content) return null;

  const contentRect = content.getBoundingClientRect();
  if (contentRect.width <= 0 || contentRect.height <= 0) return null;

  const viewportRect = viewport.getBoundingClientRect();
  return {
    contentRatioX: clampRatio((event.clientX - contentRect.left) / contentRect.width),
    contentRatioY: clampRatio((event.clientY - contentRect.top) / contentRect.height),
    viewportOffsetX: event.clientX - viewportRect.left,
    viewportOffsetY: event.clientY - viewportRect.top,
  };
}

export function restorePresentationZoomAnchor(
  viewport: HTMLElement | null,
  content: HTMLElement | null,
  anchorRef: { current: PresentationZoomAnchor | null },
) {
  const anchor = anchorRef.current;
  if (!viewport || !content || !anchor) return;

  const contentRect = content.getBoundingClientRect();
  if (contentRect.width <= 0 || contentRect.height <= 0) return;

  const viewportRect = viewport.getBoundingClientRect();
  const anchorX = contentRect.left + contentRect.width * anchor.contentRatioX;
  const anchorY = contentRect.top + contentRect.height * anchor.contentRatioY;
  viewport.scrollLeft += anchorX - (viewportRect.left + anchor.viewportOffsetX);
  viewport.scrollTop += anchorY - (viewportRect.top + anchor.viewportOffsetY);
  anchorRef.current = null;
}

export function presentationZoomStep(current: number) {
  if (current < 0.5) return 0.1;
  if (current < 2) return 0.25;
  return 0.5;
}

export function presentationThumbnailZoom(dimensions: SlideDimensions) {
  const baseSize = slideCssSize(dimensions);
  return Math.max(0.04, Math.min(0.16, 116 / baseSize.width));
}

export async function readPresentationDimensions(arrayBuffer: ArrayBuffer): Promise<SlideDimensions | null> {
  try {
    const { default: JSZip } = await import("jszip");
    const zip = await JSZip.loadAsync(arrayBuffer);
    const presentationXml = await zip.file("ppt/presentation.xml")?.async("string");
    if (!presentationXml) return null;
    return parsePresentationDimensionsXml(presentationXml);
  } catch {
    return null;
  }
}

export function repairPresentationCanvasBlankBottomEdge(canvas: HTMLCanvasElement) {
  if (canvas.width < 2 || canvas.height < 2) return;

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return;

  const bottom = context.getImageData(0, canvas.height - 1, canvas.width, 1);
  if (!isMostlyBlankOrWhitePixels(bottom.data)) return;

  const previous = context.getImageData(0, canvas.height - 2, canvas.width, 1);
  if (isMostlyBlankOrWhitePixels(previous.data)) return;

  context.putImageData(previous, 0, canvas.height - 1);
}

export function canvasToPngBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("PPT 页面图片生成失败。"));
    }, "image/png");
  });
}

export function buildPresentationSlideImageFileName(sourceFileName: string, slideNumber: number) {
  const sourceBaseName = sourceFileName.replace(/\.[^.]*$/, "") || "ppt_slide";
  const safeBaseName = sourceBaseName
    .replace(/[<>:"/\\|?*\x00-\x1F]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "ppt_slide";
  return `${safeBaseName}__ppt_slide_${String(slideNumber).padStart(3, "0")}.png`;
}

function clampRatio(value: number) {
  return Math.max(0, Math.min(1, value));
}

function parsePresentationDimensionsXml(xml: string): SlideDimensions | null {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const slideSize = doc.getElementsByTagNameNS("*", "sldSz")[0]
    ?? doc.getElementsByTagName("p:sldSz")[0]
    ?? doc.getElementsByTagName("sldSz")[0];
  if (!slideSize) return null;

  const cx = Number(slideSize.getAttribute("cx"));
  const cy = Number(slideSize.getAttribute("cy"));
  if (!Number.isFinite(cx) || !Number.isFinite(cy) || cx <= 0 || cy <= 0) return null;
  return { cx, cy };
}

function isMostlyBlankOrWhitePixels(data: Uint8ClampedArray) {
  let blankOrWhiteCount = 0;
  const pixelCount = data.length / 4;
  for (let index = 0; index < data.length; index += 4) {
    const alpha = data[index + 3] ?? 0;
    const red = data[index] ?? 0;
    const green = data[index + 1] ?? 0;
    const blue = data[index + 2] ?? 0;
    if (alpha < 8 || (red > 245 && green > 245 && blue > 245)) {
      blankOrWhiteCount += 1;
    }
  }
  return blankOrWhiteCount / pixelCount > 0.96;
}
