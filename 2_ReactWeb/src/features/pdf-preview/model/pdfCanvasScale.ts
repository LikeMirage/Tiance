type PdfCanvasViewport = {
  height: number;
  width: number;
};

const defaultMinOutputScale = 3;
const defaultMaxOutputScale = 4;
const defaultMaxCanvasPixels = 32_000_000;

export function resolvePdfCanvasOutputScale(
  viewport: PdfCanvasViewport,
  options: {
    maxCanvasPixels?: number;
    maxOutputScale?: number;
    minOutputScale?: number;
  } = {},
) {
  const minOutputScale = options.minOutputScale ?? defaultMinOutputScale;
  const maxOutputScale = options.maxOutputScale ?? defaultMaxOutputScale;
  const maxCanvasPixels = options.maxCanvasPixels ?? defaultMaxCanvasPixels;
  const devicePixelRatio = window.devicePixelRatio || 1;
  const targetScale = Math.min(
    maxOutputScale,
    Math.max(minOutputScale, devicePixelRatio * 2),
  );
  const viewportPixels = Math.max(1, viewport.width * viewport.height);
  const pixelCapScale = Math.sqrt(maxCanvasPixels / viewportPixels);

  return Math.max(1, Math.min(targetScale, pixelCapScale));
}
