import workerSrc from "pdfjs-dist/build/pdf.worker.mjs?url";

export type PdfDocumentProxy = import("pdfjs-dist").PDFDocumentProxy;
export type PdfLoadingTask = import("pdfjs-dist").PDFDocumentLoadingTask;
export type PdfJsLib = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<PdfJsLib> | null = null;

export function loadPdfJs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import("pdfjs-dist").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;
      return pdfjs;
    });
  }
  return pdfjsPromise;
}
