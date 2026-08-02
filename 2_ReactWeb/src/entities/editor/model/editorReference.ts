export type EditorTextReferenceSource =
  | "source"
  | "markdown_preview"
  | "markdown_visual"
  | "pdf"
  | "office";

export type EditorTextReferenceDraft = {
  content: string;
  displayPath: string;
  endLine?: number;
  fileName: string;
  filePath: string;
  projectId: string | null;
  source: EditorTextReferenceSource;
  startLine?: number;
};

export type EditorTextReference = EditorTextReferenceDraft & {
  id: string;
};

export type EditorImageReferenceSource = "pdf_page" | "ppt_slide" | "xlsx_range";

export type EditorImageReferenceDraft = {
  displayPath: string;
  fileName: string;
  filePath: string;
  imagePath: string;
  mimeType: string;
  cells?: string[][];
  pageNumber?: number;
  projectId: string | null;
  rangeAddress?: string;
  sizeBytes: number;
  sheetName?: string;
  slideNumber?: number;
  source: EditorImageReferenceSource;
  sourceDisplayPath: string;
  sourceFileName: string;
  sourceFilePath: string;
};

export type EditorImageReference = EditorImageReferenceDraft & {
  id: string;
};

export type EditorFileReferenceSource = "external_path" | "project_file";

export type EditorExternalPathReferenceRequest = {
  kind: "file" | "folder";
  name: string;
  path: string;
};

export type EditorFileReference = {
  displayPath: string;
  fileName: string;
  filePath: string;
  id: string;
  kind: "file" | "folder";
  projectId: string | null;
  source: EditorFileReferenceSource;
};

export type EditorReferenceViewerPayload =
  | {
    kind: "file";
    reference: EditorFileReference;
  }
  | {
    kind: "image";
    reference: EditorImageReference;
  }
  | {
    kind: "text";
    reference: EditorTextReference;
  };

export type EditorPdfPageImageReferenceRequest = {
  file: File;
  pageNumber: number;
  projectId: string | null;
  sourceDisplayPath: string;
  sourceFileName: string;
  sourceFilePath: string;
};

export type EditorPresentationSlideImageReferenceRequest = {
  file: File;
  projectId: string | null;
  slideNumber: number;
  sourceDisplayPath: string;
  sourceFileName: string;
  sourceFilePath: string;
};

export type EditorSpreadsheetRangeImageReferenceRequest = {
  cells: string[][];
  file: File;
  projectId: string | null;
  rangeAddress: string;
  sheetName: string;
  sourceDisplayPath: string;
  sourceFileName: string;
  sourceFilePath: string;
};
