import { useMemo } from "react";

import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import { textReferenceLocationLabel } from "../../../entities/editor/model/editorTextReferenceLocation";
import { createWorkspaceAssetUrl } from "../../document-editor-canvas/model/documentAssetUrls";
import { ImagePreview } from "../../document-editor-canvas/ui/ImagePreview";
import "./reference-viewer.css";

type ReferenceViewerProps = {
  content: string;
};

export function ReferenceViewer({ content }: ReferenceViewerProps) {
  const payload = useMemo(() => parsePayload(content), [content]);
  if (!payload) {
    return (
      <div className="reference-viewer reference-viewer--empty">
        <div className="reference-viewer__empty">引用内容无法读取。</div>
      </div>
    );
  }

  return (
    <div className="reference-viewer">
      <ReferenceHeader payload={payload} />
      <ReferenceDetails payload={payload} />
      <div className="reference-viewer__body">
        <ReferencePreview payload={payload} />
      </div>
    </div>
  );
}

function ReferenceHeader({ payload }: { payload: EditorReferenceViewerPayload }) {
  return (
    <header className="reference-viewer__header">
      <div className="reference-viewer__heading">
        <span className="reference-viewer__kind">{referenceKindLabel(payload)}</span>
        <h2>{referenceTitle(payload)}</h2>
      </div>
      <div className="reference-viewer__path" title={referencePrimaryPath(payload)}>
        {referencePrimaryPath(payload)}
      </div>
    </header>
  );
}

function ReferencePreview({ payload }: { payload: EditorReferenceViewerPayload }) {
  if (payload.kind === "text") {
    return (
      <section className="reference-viewer__preview reference-viewer__preview--text">
        <pre>{payload.reference.content}</pre>
      </section>
    );
  }

  const image = resolveReferenceImage(payload);
  if (image) {
    return (
      <ImagePreview
        displayPath={image.path}
        fileName={image.name}
        src={image.src}
      />
    );
  }

  return (
    <section className="reference-viewer__preview reference-viewer__preview--placeholder">
      <div>
        <strong>{payload.kind === "file" ? payload.reference.fileName : payload.reference.sourceFileName}</strong>
        <span>{payload.kind === "file" ? payload.reference.kind : payload.reference.source}</span>
      </div>
    </section>
  );
}

function ReferenceDetails({ payload }: { payload: EditorReferenceViewerPayload }) {
  const rows = referenceRows(payload);
  const cells = payload.kind === "image" && payload.reference.cells?.length
    ? payload.reference.cells
    : null;
  return (
    <aside className="reference-viewer__details">
      <div className="reference-viewer__details-grid">
        {rows.map((row) => (
          <div className="reference-viewer__detail-row" key={row.label}>
            <span>{row.label}</span>
            <strong title={row.value}>{row.value || "-"}</strong>
          </div>
        ))}
      </div>
      {cells ? (
        <div className="reference-viewer__table-wrap">
          <table className="reference-viewer__table">
            <tbody>
              {cells.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </aside>
  );
}

function parsePayload(content: string): EditorReferenceViewerPayload | null {
  try {
    const payload = JSON.parse(content) as EditorReferenceViewerPayload;
    if (
      payload &&
      (payload.kind === "file" || payload.kind === "image" || payload.kind === "text") &&
      payload.reference
    ) {
      return payload;
    }
  } catch {
    return null;
  }
  return null;
}

function referenceKindLabel(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "text") return "文本选区";
  if (payload.kind === "file") return payload.reference.kind === "folder" ? "文件夹引用" : "文件引用";
  switch (payload.reference.source) {
    case "pdf_page":
      return "PDF 页面";
    case "ppt_slide":
      return "PPT 幻灯片";
    case "xlsx_range":
      return "Excel 区域";
    default:
      return "图片引用";
  }
}

function referenceTitle(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "image") {
    return payload.reference.sourceFileName;
  }
  return payload.reference.fileName;
}

function referencePrimaryPath(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "image") return payload.reference.imagePath;
  return payload.reference.filePath;
}

function referenceRows(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "text") {
    const rows = [
      { label: "来源", value: payload.reference.fileName },
      { label: "路径", value: payload.reference.filePath },
      { label: "位置", value: textReferenceLocationLabel(payload.reference) },
      { label: "类型", value: referenceKindLabel(payload) },
    ];
    if (payload.reference.location?.nearestHeading) {
      rows.push({ label: "章节", value: payload.reference.location.nearestHeading });
    }
    return rows;
  }

  if (payload.kind === "file") {
    return [
      { label: "名称", value: payload.reference.fileName },
      { label: "路径", value: payload.reference.filePath },
      { label: "类型", value: payload.reference.kind === "folder" ? "文件夹" : "文件" },
      { label: "来源", value: payload.reference.source === "external_path" ? "外部路径" : "当前项目" },
    ];
  }

  const rows = [
    { label: "来源", value: payload.reference.sourceFileName },
    { label: "源路径", value: payload.reference.sourceFilePath },
    { label: "图片", value: payload.reference.imagePath },
    { label: "类型", value: referenceKindLabel(payload) },
  ];
  if (payload.reference.pageNumber) rows.push({ label: "页码", value: String(payload.reference.pageNumber) });
  if (payload.reference.slideNumber) rows.push({ label: "幻灯片", value: String(payload.reference.slideNumber) });
  if (payload.reference.sheetName) rows.push({ label: "Sheet", value: payload.reference.sheetName });
  if (payload.reference.rangeAddress) rows.push({ label: "范围", value: payload.reference.rangeAddress });
  return rows;
}

function resolveReferenceImage(payload: EditorReferenceViewerPayload) {
  if (payload.kind === "text") return null;
  const projectId = payload.reference.projectId;
  if (!projectId) return null;
  const path = payload.kind === "image"
    ? payload.reference.imagePath
    : payload.reference.filePath;
  if (!isSupportedImagePath(path, payload.kind === "image" ? payload.reference.mimeType : undefined)) {
    return null;
  }
  const src = createWorkspaceAssetUrl({
    id: projectId,
    key: `project:${projectId}`,
    kind: "project",
    label: "项目",
  }, path);
  return src ? { name: referenceTitle(payload), path, src } : null;
}

function isSupportedImagePath(path: string, mimeType?: string) {
  const normalizedMime = mimeType?.split(";", 1)[0]?.trim().toLowerCase();
  if (normalizedMime?.startsWith("image/")) return true;
  return /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(path);
}
