import { lazy, useEffect, useRef, useState } from "react";
import type { Dispatch, MouseEvent, SetStateAction } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import type { EditorTextReferenceSource } from "../../../entities/editor/model/editorReference";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import type { CodeEditorTextSelectionContextMenu } from "../../editor/ui/CodeEditor";
import { EditorLazyBoundary } from "./EditorContentBoundary";
import { previewPolicy } from "../../file-preview/model/previewPolicy";
import { useDocumentReadingScroll } from "../../../entities/editor/model/documentReadingState";

const CodeEditor = lazy(() =>
  import("../../editor/ui/CodeEditor").then((module) => ({ default: module.CodeEditor })),
);
const MarkdownVisualEditor = lazy(() =>
  import("../../markdown-visual-editor/ui/MarkdownVisualEditor").then((module) => ({
    default: module.MarkdownVisualEditor,
  })),
);

export type MarkdownEditorMode = "source" | "preview" | "visual";
export type MarkdownDocxGenerationResult = {
  outputPath: string;
  warnings: string[];
};

export function MarkdownDocumentContent({
  activeTab,
  boundaryKey,
  markdownAssetUrlResolver,
  markdownMode,
  onEditorScroll,
  onEditorScrollerReady,
  onMarkDirty,
  onRenderedTextContextMenu,
  onSaveCodeBlock,
  onSaveTab,
  onSourceTextContextMenu,
  onGenerateDocx,
  onUpdateContent,
  setMarkdownMode,
}: {
  activeTab: DocumentTab;
  boundaryKey: string;
  markdownAssetUrlResolver?: (src: string | undefined) => string | undefined;
  markdownMode: MarkdownEditorMode;
  onEditorScroll: (scroller: HTMLElement) => void;
  onEditorScrollerReady: (scroller: HTMLElement | null) => void;
  onMarkDirty: (id: string) => void;
  onRenderedTextContextMenu: (
    event: MouseEvent<HTMLElement>,
    source: EditorTextReferenceSource,
  ) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  onSaveTab: (id: string, contentSnapshot?: string) => Promise<boolean>;
  onSourceTextContextMenu: (
    selection: CodeEditorTextSelectionContextMenu,
    source?: EditorTextReferenceSource,
  ) => void;
  onGenerateDocx?: (tab: DocumentTab) => Promise<MarkdownDocxGenerationResult>;
  onUpdateContent: (id: string, content: string) => void;
  setMarkdownMode: Dispatch<SetStateAction<MarkdownEditorMode>>;
}) {
  const visualBudgetExceeded = activeTab.content.length > previewPolicy.richTextCharacters;
  const effectiveMode = visualBudgetExceeded && markdownMode === "visual" ? "source" : markdownMode;
  const renderMode = effectiveMode;
  const [docxState, setDocxState] = useState<{
    message: string;
    state: "idle" | "running" | "success" | "error";
  }>({ message: "", state: "idle" });
  const docxStatusTimerRef = useRef<number | null>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  useDocumentReadingScroll("markdown-preview", previewScrollRef,
    renderMode === "preview", activeTab.content);
  const updateCurrentContent = (content: string) => onUpdateContent(activeTab.id, content);
  const markCurrentDirty = () => onMarkDirty(activeTab.id);
  const saveCurrentTab = (content: string) => void onSaveTab(activeTab.id, content);
  const requestMarkdownMode = (nextMode: MarkdownEditorMode) => setMarkdownMode(nextMode);

  const setTemporaryDocxState = (state: "success" | "error", message: string) => {
    if (docxStatusTimerRef.current !== null) {
      window.clearTimeout(docxStatusTimerRef.current);
    }
    setDocxState({ message, state });
    docxStatusTimerRef.current = window.setTimeout(() => {
      setDocxState({ message: "", state: "idle" });
      docxStatusTimerRef.current = null;
    }, 2600);
  };

  const generateDocx = async () => {
    if (!onGenerateDocx || docxState.state === "running") return;
    if (docxStatusTimerRef.current !== null) {
      window.clearTimeout(docxStatusTimerRef.current);
      docxStatusTimerRef.current = null;
    }
    setDocxState({ message: "正在生成 Word", state: "running" });
    try {
      const result = await onGenerateDocx(activeTab);
      const warningText = result.warnings.length > 0 ? `，警告 ${result.warnings.length} 条` : "";
      setTemporaryDocxState("success", `已生成：${result.outputPath}${warningText}`);
    } catch (error) {
      setTemporaryDocxState("error", error instanceof Error ? error.message : "Word 生成失败。");
    }
  };

  useEffect(() => () => {
    if (docxStatusTimerRef.current !== null) {
      window.clearTimeout(docxStatusTimerRef.current);
    }
  }, []);

  const wordButtonLabel = docxState.state === "running"
    ? "生成中"
    : docxState.state === "success"
      ? "已生成"
      : docxState.state === "error"
        ? "失败"
        : "Word";

  return (
    <>
      {renderMode === "preview" ? (
        <div
          ref={previewScrollRef}
          className="doc-editor__preview doc-editor__preview--markdown-full"
          onContextMenu={(event) => onRenderedTextContextMenu(event, "markdown_preview")}
        >
          <LazyMarkdownPreview
            content={activeTab.content}
            onSaveCodeBlock={onSaveCodeBlock}
            renderStrategy="progressive"
            resolveAssetUrl={markdownAssetUrlResolver}
          />
        </div>
      ) : renderMode === "visual" && !visualBudgetExceeded ? (
        <div
          className="doc-editor__markdown-visual"
          onContextMenu={(event) => onRenderedTextContextMenu(event, "markdown_visual")}
        >
          <EditorLazyBoundary resetKey={boundaryKey}>
            <MarkdownVisualEditor
              value={activeTab.content}
              resolveAssetUrl={markdownAssetUrlResolver}
              onChange={updateCurrentContent}
              onDirty={markCurrentDirty}
              onSave={saveCurrentTab}
            />
          </EditorLazyBoundary>
        </div>
      ) : (
        <div className="doc-editor__full">
          <div className="doc-editor__source">
            <EditorLazyBoundary resetKey={boundaryKey}>
              <CodeEditor
                value={activeTab.content}
                languageId={activeTab.languageId}
                onChange={updateCurrentContent}
                onDirty={markCurrentDirty}
                onSave={saveCurrentTab}
                onScrollerReady={onEditorScrollerReady}
                onScroll={onEditorScroll}
                onTextSelectionContextMenu={(selection) => onSourceTextContextMenu(selection, "source")}
              />
            </EditorLazyBoundary>
          </div>
        </div>
      )}

      <div className="doc-editor__markdown-mode-controls" aria-label="Markdown 查看模式">
        <MarkdownModeButton
          active={markdownMode === "preview"}
          label="预览"
          onClick={() => requestMarkdownMode("preview")}
        />
        <MarkdownModeButton
          active={markdownMode === "visual"}
          label="编辑"
          onClick={() => requestMarkdownMode("visual")}
        />
        <MarkdownModeButton
          active={markdownMode === "source"}
          label="源码"
          onClick={() => requestMarkdownMode("source")}
        />
        {onGenerateDocx ? (
          <MarkdownModeButton
            active={false}
            disabled={docxState.state === "running"}
            label={wordButtonLabel}
            title={docxState.message || "生成 Word"}
            onClick={() => void generateDocx()}
          />
        ) : null}
      </div>
    </>
  );
}

function MarkdownModeButton({
  active,
  disabled = false,
  label,
  onClick,
  title,
}: {
  active: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      className={active ? "doc-editor__markdown-mode doc-editor__markdown-mode--active" : "doc-editor__markdown-mode"}
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      title={title}
    >
      {label}
    </button>
  );
}
