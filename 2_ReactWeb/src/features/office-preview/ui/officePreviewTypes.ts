import type { PPTXViewer as PPTXViewerInstance } from "pptxviewjs";

export type PresentationSlideImageReferencePayload = {
  file: File;
  slideNumber: number;
  sourceDisplayPath: string;
  sourceFileName: string;
};

export type LoadState = "idle" | "loading" | "ready" | "error";
export type OfficeKind = "word" | "spreadsheet" | "presentation" | "unsupported";
export type OfficeLoadingVisibilityChange = (visible: boolean) => void;
export type SlideDimensions = { cx: number; cy: number };

export const officePreviewMinimumLoadingMs = 260;

export type PPTXViewerWithDimensions = PPTXViewerInstance & {
  getSlideDimensions?: () => SlideDimensions;
};

export type PresentationZoomAnchor = {
  contentRatioX: number;
  contentRatioY: number;
  viewportOffsetX: number;
  viewportOffsetY: number;
};
