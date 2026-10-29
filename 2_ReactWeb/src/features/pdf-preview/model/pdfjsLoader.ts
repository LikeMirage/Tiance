import workerSrc from "pdfjs-dist/build/pdf.worker.mjs?url";

export type PdfDocumentProxy = import("pdfjs-dist").PDFDocumentProxy;
export type PdfLoadingTask = import("pdfjs-dist").PDFDocumentLoadingTask;
export type PdfJsLib = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<PdfJsLib> | null = null;

export class PdfModuleLoadError extends Error {
  constructor(cause: unknown) {
    super("PDF 预览模块加载失败，请重试；若仍失败，可保存编辑内容后重新加载界面。", { cause });
    this.name = "PdfModuleLoadError";
  }
}

export function loadPdfJs() {
  if (!pdfjsPromise) {
    const attempt = import("pdfjs-dist").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;
      return pdfjs;
    }).catch((cause: unknown) => {
      if (pdfjsPromise === attempt) pdfjsPromise = null;
      throw new PdfModuleLoadError(cause);
    });
    pdfjsPromise = attempt;
  }
  return pdfjsPromise;
}
