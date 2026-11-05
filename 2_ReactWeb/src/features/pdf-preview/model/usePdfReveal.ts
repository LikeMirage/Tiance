import { useEffect, useRef, type RefObject } from "react";
import { useDocumentRevealRequest } from "../../../entities/editor/model/documentRevealContext";
import { DocumentRevealError, type DocumentRevealRequest } from "../../../entities/editor/model/documentReveal";
import type { PdfDocumentProxy } from "./pdfjsLoader";

export type PdfPageRenderState = {
  document: PdfDocumentProxy;
  page: number;
  scale: number;
  state: "loading" | "ready" | "error";
  error?: string;
};

export function usePdfReveal({ pdfDocument, errorMessage, currentPage, scale, rendered, selectPage, viewport, stopReadingRestore }: {
  pdfDocument: PdfDocumentProxy | null;
  errorMessage: string | null;
  currentPage: number;
  scale: number;
  rendered: PdfPageRenderState | null;
  selectPage: (page: number, signal?: AbortSignal) => void;
  viewport: RefObject<HTMLDivElement | null>;
  stopReadingRestore: () => void;
}) {
  const request = useDocumentRevealRequest();
  const started = useRef<DocumentRevealRequest | null>(null);
  useEffect(() => {
    if (!request || request.signal.aborted || request.target.type !== "pdf_page") return;
    if (errorMessage) { request.fail(new DocumentRevealError("LOAD_FAILED", errorMessage)); return; }
    if (!pdfDocument) return;
    if (request.target.page > pdfDocument.numPages) {
      request.fail(new DocumentRevealError("PAGE_OUT_OF_RANGE", `页码超出范围，PDF 共 ${pdfDocument.numPages} 页。`, { total_pages: pdfDocument.numPages }));
      return;
    }
    if (started.current !== request) {
      started.current = request;
      stopReadingRestore();
      selectPage(request.target.page, request.signal);
    }
  }, [request, pdfDocument, errorMessage, selectPage, stopReadingRestore]);

  useEffect(() => {
    if (!request || request.signal.aborted || request.target.type !== "pdf_page" || !pdfDocument
      || rendered?.document !== pdfDocument || rendered.page !== request.target.page
      || currentPage !== request.target.page || rendered.scale !== scale) return;
    if (rendered.state === "error") {
      request.fail(new DocumentRevealError("RENDER_FAILED", rendered.error ?? "PDF 页面渲染失败。"));
      return;
    }
    if (rendered.state !== "ready") return;
    const page = request.target.page;
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        const element = viewport.current;
        if (!element || request.signal.aborted) return;
        stopReadingRestore();
        element.scrollTop = Math.max(0, (element.scrollHeight - element.clientHeight) / 2);
        element.scrollLeft = Math.max(0, (element.scrollWidth - element.clientWidth) / 2);
        request.complete({ type: "pdf_page", page, total_pages: pdfDocument.numPages });
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [request, pdfDocument, rendered, currentPage, scale, viewport, stopReadingRestore]);
}
