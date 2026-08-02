import type { PdfDocumentProxy } from "./pdfjsLoader";
import { resolvePdfCanvasOutputScale } from "./pdfCanvasScale";

type RenderPdfPageImageOptions = {
  pageNumber: number;
  pdfDocument: PdfDocumentProxy;
  sourceFileName: string;
};

const maxPageImageCanvasPixels = 24_000_000;
const maxPageImageOutputScale = 3;
const minPageImageOutputScale = 3;

export type PdfPageImageReferencePayload = {
  file: File;
  pageNumber: number;
  sourceDisplayPath: string;
  sourceFileName: string;
};

export async function renderPdfPageToPngFile({
  pageNumber,
  pdfDocument,
  sourceFileName,
}: RenderPdfPageImageOptions) {
  const page = await pdfDocument.getPage(pageNumber);
  const baseViewport = page.getViewport({ scale: 1 });
  const outputScale = resolvePdfCanvasOutputScale(baseViewport, {
    maxCanvasPixels: maxPageImageCanvasPixels,
    maxOutputScale: maxPageImageOutputScale,
    minOutputScale: minPageImageOutputScale,
  });
  const viewport = page.getViewport({ scale: outputScale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);

  const renderTask = page.render({
    canvas,
    viewport,
  });
  await renderTask.promise;

  const blob = await canvasToPngBlob(canvas);
  canvas.width = 0;
  canvas.height = 0;
  return new File([blob], buildPdfPageImageFileName(sourceFileName, pageNumber), {
    type: "image/png",
  });
}

function canvasToPngBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("PDF 页面图片生成失败。"));
    }, "image/png");
  });
}

function buildPdfPageImageFileName(sourceFileName: string, pageNumber: number) {
  const sourceBaseName = sourceFileName.replace(/\.[^.]*$/, "") || "pdf_page";
  const safeBaseName = sourceBaseName
    .replace(/[<>:"/\\|?*\x00-\x1F]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "pdf_page";
  return `${safeBaseName}__pdf_page_${String(pageNumber).padStart(3, "0")}.png`;
}
