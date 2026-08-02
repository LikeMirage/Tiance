import type { PdfDocumentProxy } from "./pdfjsLoader";

type RefProxy = {
  gen: number;
  num: number;
};

type EventBusLike = {
  dispatch: (eventName: string, data: Record<string, unknown>) => void;
};

export type PdfLinkServiceLike = {
  eventBus: EventBusLike;
  externalLinkEnabled: boolean;
  addLinkAttributes: (link: HTMLAnchorElement, url: string, newWindow?: boolean) => void;
  executeNamedAction: (action: string) => void;
  executeSetOCGState: () => Promise<void>;
  getAnchorUrl: (anchor: string) => string;
  getDestinationHash: (destination: string | unknown[]) => string;
  goToDestination: (destination: string | unknown[]) => Promise<void>;
  goToPage: (value: number | string) => void;
};

export type PdfDownloadManagerLike = {
  download: (data: Uint8Array | null, url: string, fileName: string) => void;
  downloadData: (data: Uint8Array, fileName: string, contentType?: string) => void;
  openOrDownloadData: (data: Uint8Array, fileName: string, destination?: string | null) => boolean;
};

type PdfLinkAdapterOptions = {
  currentPageNumber: number;
  onPageChange: (pageNumber: number) => void;
  pdfDocument: PdfDocumentProxy;
};

const externalLinkRel = "noopener noreferrer nofollow";

export function createPdfLinkService({
  currentPageNumber,
  onPageChange,
  pdfDocument,
}: PdfLinkAdapterOptions): PdfLinkServiceLike {
  const goToPage = (value: number | string) => {
    const pageNumber = typeof value === "string" ? Number.parseInt(value, 10) : value;
    if (!Number.isInteger(pageNumber)) return;
    onPageChange(clampPage(pageNumber, pdfDocument.numPages));
  };

  return {
    eventBus: {
      dispatch: () => undefined,
    },
    externalLinkEnabled: true,
    addLinkAttributes(link, url, newWindow = false) {
      if (!url) return;
      const safeUrl = stripCredentialsFromUrl(url);
      link.href = safeUrl;
      link.title = safeUrl;
      link.rel = externalLinkRel;
      link.target = newWindow ? "_blank" : "_blank";
    },
    executeNamedAction(action) {
      if (action === "NextPage") {
        goToPage(currentPageNumber + 1);
        return;
      }
      if (action === "PrevPage") {
        goToPage(currentPageNumber - 1);
        return;
      }
      if (action === "FirstPage") {
        goToPage(1);
        return;
      }
      if (action === "LastPage") {
        goToPage(pdfDocument.numPages);
      }
    },
    async executeSetOCGState() {
      await Promise.resolve();
    },
    getAnchorUrl(anchor) {
      return anchor || "#";
    },
    getDestinationHash(destination) {
      if (typeof destination === "string") {
        return destination ? `#${encodeURIComponent(destination)}` : "#";
      }
      return "#";
    },
    async goToDestination(destination) {
      const pageNumber = await resolveDestinationPageNumber(pdfDocument, destination);
      if (!pageNumber) return;
      onPageChange(clampPage(pageNumber, pdfDocument.numPages));
    },
    goToPage,
  };
}

export function createPdfDownloadManager(): PdfDownloadManagerLike {
  return {
    download(data, url, fileName) {
      if (data) {
        downloadBinary(data, fileName, "application/pdf");
        return;
      }
      triggerDownload(url, fileName);
    },
    downloadData(data, fileName, contentType = "application/octet-stream") {
      downloadBinary(data, fileName, contentType);
    },
    openOrDownloadData(data, fileName) {
      downloadBinary(data, fileName, "application/octet-stream");
      return false;
    },
  };
}

async function resolveDestinationPageNumber(
  pdfDocument: PdfDocumentProxy,
  destination: string | unknown[],
) {
  const explicitDestination = typeof destination === "string"
    ? await pdfDocument.getDestination(destination)
    : destination;
  if (!Array.isArray(explicitDestination)) return null;

  const destinationRef = explicitDestination[0];
  if (Number.isInteger(destinationRef)) {
    return Number(destinationRef) + 1;
  }
  if (!isRefProxy(destinationRef)) {
    return null;
  }

  const cachedPageNumber = pdfDocument.cachedPageNumber(destinationRef);
  if (cachedPageNumber) return cachedPageNumber;

  return (await pdfDocument.getPageIndex(destinationRef)) + 1;
}

function isRefProxy(value: unknown): value is RefProxy {
  return (
    typeof value === "object"
    && value !== null
    && Number.isInteger((value as RefProxy).num)
    && Number.isInteger((value as RefProxy).gen)
  );
}

function clampPage(pageNumber: number, numPages: number) {
  return Math.max(1, Math.min(numPages || 1, pageNumber));
}

function stripCredentialsFromUrl(url: string) {
  try {
    const parsedUrl = new URL(url);
    parsedUrl.username = "";
    parsedUrl.password = "";
    return parsedUrl.href;
  } catch {
    return url;
  }
}

function downloadBinary(data: Uint8Array, fileName: string, contentType: string) {
  const blobUrl = URL.createObjectURL(new Blob([data as BlobPart], { type: contentType }));
  triggerDownload(blobUrl, fileName);
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
}

function triggerDownload(url: string, fileName: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
}
