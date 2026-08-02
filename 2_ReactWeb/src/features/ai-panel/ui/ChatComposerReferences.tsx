import { File, Folder, ImageSquare, Quotes, X } from "@phosphor-icons/react";
import type { ReactNode } from "react";

import type {
  EditorFileReference,
  EditorImageReference,
  EditorReferenceViewerPayload,
  EditorTextReference,
} from "../../../entities/editor/model/editorReference";
import type {
  ConversationMessageReference,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";

export function ChatComposerReferences({
  onRemoveFile,
  onRemoveImage,
  onRemoveText,
  onOpenReference,
  references,
}: {
  onRemoveFile: ((referenceId: string) => void) | undefined;
  onRemoveImage: ((referenceId: string) => void) | undefined;
  onRemoveText: ((referenceId: string) => void) | undefined;
  onOpenReference: ((payload: EditorReferenceViewerPayload) => void) | undefined;
  references: ConversationMessageReferences | undefined;
}) {
  const totalCount = references?.length ?? 0;
  if (totalCount === 0) {
    return null;
  }

  const canClear = Boolean(onRemoveFile || onRemoveImage || onRemoveText);

  return (
    <section className="ai-panel__references" aria-label="已引用内容">
      <div className="ai-panel__references-head">
        <span>引用 {totalCount}</span>
        {canClear ? (
          <button
            className="ai-panel__references-clear"
            type="button"
            onClick={() => {
              references?.forEach((item) => {
                if (item.type === "file") onRemoveFile?.(item.reference.id);
                if (item.type === "image") onRemoveImage?.(item.reference.id);
                if (item.type === "text") onRemoveText?.(item.reference.id);
              });
            }}
          >
            清空
          </button>
        ) : null}
      </div>
      <div className="ai-panel__references-list">
        {references?.map((item, index) => (
          <OrderedReferenceRow
            index={index + 1}
            item={item}
            key={item.reference.id}
            onOpenReference={onOpenReference}
            onRemoveFile={onRemoveFile}
            onRemoveImage={onRemoveImage}
            onRemoveText={onRemoveText}
          />
        ))}
      </div>
    </section>
  );
}

function OrderedReferenceRow({
  index,
  item,
  onOpenReference,
  onRemoveFile,
  onRemoveImage,
  onRemoveText,
}: {
  index: number;
  item: ConversationMessageReference;
  onOpenReference: ((payload: EditorReferenceViewerPayload) => void) | undefined;
  onRemoveFile: ((referenceId: string) => void) | undefined;
  onRemoveImage: ((referenceId: string) => void) | undefined;
  onRemoveText: ((referenceId: string) => void) | undefined;
}) {
  if (item.type === "file") {
    const reference = item.reference;
    return <ReferenceRow
      detail={reference.filePath}
      icon={reference.kind === "folder" ? <Folder size={15} weight="bold" /> : <File size={15} weight="bold" />}
      index={index}
      meta={formatFileReferenceMeta(reference)}
      title={reference.fileName}
      onOpen={onOpenReference ? () => onOpenReference({ kind: "file", reference }) : undefined}
      onRemove={onRemoveFile ? () => onRemoveFile(reference.id) : undefined}
    />;
  }
  if (item.type === "image") {
    const reference = item.reference;
    return <ReferenceRow
      detail={reference.imagePath}
      icon={<ImageSquare size={15} weight="bold" />}
      index={index}
      meta={formatImageReferenceMeta(reference)}
      title={reference.sourceFileName}
      onOpen={onOpenReference ? () => onOpenReference({ kind: "image", reference }) : undefined}
      onRemove={onRemoveImage ? () => onRemoveImage(reference.id) : undefined}
    />;
  }
  const reference = item.reference;
  return <ReferenceRow
    detail={formatTextReferencePreview(reference.content)}
    icon={<Quotes size={15} weight="bold" />}
    index={index}
    meta={formatTextReferenceMeta(reference)}
    title={reference.fileName}
    onOpen={onOpenReference ? () => onOpenReference({ kind: "text", reference }) : undefined}
    onRemove={onRemoveText ? () => onRemoveText(reference.id) : undefined}
  />;
}

function ReferenceRow({
  detail,
  icon,
  index,
  meta,
  onOpen,
  onRemove,
  title,
}: {
  detail: string;
  icon: ReactNode;
  index: number;
  meta: string;
  onOpen?: () => void;
  onRemove?: () => void;
  title: string;
}) {
  return (
    <div className="ai-panel__reference">
      <button
        className={onOpen ? "ai-panel__reference-open" : "ai-panel__reference-open ai-panel__reference-open--static"}
        disabled={!onOpen}
        title={onOpen ? "查看引用内容" : undefined}
        type="button"
        onClick={onOpen}
      >
        <span className="ai-panel__reference-index">No. {index}</span>
        <span className="ai-panel__reference-icon" aria-hidden="true">{icon}</span>
        <div className="ai-panel__reference-body">
          <div className="ai-panel__reference-line">
            <strong title={title}>{title}</strong>
            <span>{meta}</span>
          </div>
          <div className="ai-panel__reference-detail" title={detail}>{detail}</div>
        </div>
      </button>
      {onRemove ? (
        <button
          className="ai-panel__reference-remove"
          title="移除引用"
          type="button"
          onClick={onRemove}
        >
          <X size={13} weight="bold" />
        </button>
      ) : null}
    </div>
  );
}

function formatTextReferenceMeta(reference: EditorTextReference) {
  if (reference.startLine && reference.endLine) {
    return reference.startLine === reference.endLine
      ? `L${reference.startLine}`
      : `L${reference.startLine}-L${reference.endLine}`;
  }
  if (reference.source === "markdown_preview") return "Markdown 预览";
  if (reference.source === "markdown_visual") return "Markdown 编辑";
  if (reference.source === "pdf") return "PDF 选区";
  if (reference.source === "office") return "文档选区";
  return "文本选区";
}

function formatImageReferenceMeta(reference: EditorImageReference) {
  if (reference.source === "pdf_page" && reference.pageNumber) {
    return `PDF 第 ${reference.pageNumber} 页`;
  }
  if (reference.source === "ppt_slide" && reference.slideNumber) {
    return `PPT 第 ${reference.slideNumber} 页`;
  }
  if (reference.source === "xlsx_range") {
    const cells = reference.cells;
    const rowCount = cells?.length ?? 0;
    const columnCount = resolveMaxColumnCount(cells);
    const sizeText = rowCount > 0 && columnCount > 0 ? ` · ${rowCount}x${columnCount}` : "";
    return `Excel ${reference.sheetName ?? "Sheet"} ${reference.rangeAddress ?? "选区"}${sizeText}`;
  }
  return "图片引用";
}

function resolveMaxColumnCount(cells: string[][] | undefined) {
  if (!cells?.length) return 0;
  let maxColumnCount = 0;
  for (const row of cells) {
    if (row.length > maxColumnCount) {
      maxColumnCount = row.length;
    }
  }
  return maxColumnCount;
}

function formatFileReferenceMeta(reference: EditorFileReference) {
  const kindText = reference.kind === "folder" ? "文件夹" : "文件";
  return reference.source === "external_path" ? `外部${kindText}` : `工作区${kindText}`;
}

function formatTextReferencePreview(content: string) {
  const compact = content.replace(/\s+/g, " ").trim();
  return compact;
}
