import { useEffect, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { ChatCircleText, Check, Copy } from "@phosphor-icons/react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { getEditorDocumentPath } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorTextReferenceDraft,
  EditorTextReferenceSource,
  EditorWordTextReferenceLocation,
} from "../../../entities/editor/model/editorReference";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import { useI18n } from "../../../shared/i18n";
import type { CodeEditorTextSelectionContextMenu } from "../../editor/ui/CodeEditor";
import { readWordTextReferenceLocation } from "../model/wordTextReferenceLocation";
import { renderedSelectionMarkdown } from "../model/renderedSelectionMarkdown";

import { useDocumentMarks } from "../../editor/model/DocumentMarksContext";
import type { DocumentMark } from "../../editor/model/documentMarks";
import { previewAnchor } from "../model/previewMarkText";

type TextReferenceMenuState = {
  marks?: DocumentMark[];
  selectedText: string;
  copyFailed?: boolean;
  reference: EditorTextReferenceDraft;
  x: number;
  y: number;
} | null;

type UseDocumentTextReferenceMenuOptions = {
  activeTab: DocumentTab | null;
  onCreateTextReference?: (reference: EditorTextReferenceDraft) => void;
};

export function useDocumentTextReferenceMenu({
  activeTab,
  onCreateTextReference,
}: UseDocumentTextReferenceMenuOptions) {
  const { t } = useI18n();
  const markState = useDocumentMarks();
  const [textReferenceMenu, setTextReferenceMenu] = useState<TextReferenceMenuState>(null);

  useEffect(() => {
    setTextReferenceMenu(null);
  }, [activeTab?.id]);

  const openTextReferenceMenu = (
    selection: {
      marks?: DocumentMark[];
      content: string;
      contentMarkdown?: string;
      documentFingerprint?: string;
      endLine?: number;
      pageNumber?: number;
      location?: EditorWordTextReferenceLocation;
      startLine?: number;
      x: number;
      y: number;
    },
    source: EditorTextReferenceSource,
  ) => {
    if (!activeTab || !selection.content) return;
    const content = selection.content.trim();
    setTextReferenceMenu({
      selectedText: selection.content,
      marks: selection.marks,
      reference: buildEditorTextReferenceDraft(activeTab, {
        content,
        contentMarkdown: selection.contentMarkdown,
        documentFingerprint: selection.documentFingerprint,
        endLine: selection.endLine,
        pageNumber: selection.pageNumber,
        location: selection.location,
        source,
        startLine: selection.startLine,
      }),
      x: selection.x,
      y: selection.y,
    });
  };

  const copySelection = async (menu: NonNullable<TextReferenceMenuState>) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(menu.selectedText);
      } else if (window.getSelection()?.toString() !== menu.selectedText || !document.execCommand("copy")) {
        // Plain HTTP only supports native copying while the original selection is live.
        throw new Error("Clipboard unavailable");
      }
    } catch {
      setTextReferenceMenu(current => current === menu ? { ...menu, copyFailed: true } : current);
      return;
    }
    setTextReferenceMenu(current => current === menu ? null : current);
  };

  const handleSourceTextContextMenu = (
    selection: CodeEditorTextSelectionContextMenu,
    source: EditorTextReferenceSource = "source",
  ) => {
    openTextReferenceMenu(selection, source);
  };

  const handleRenderedTextContextMenu = (
    event: MouseEvent<HTMLElement>,
    source: EditorTextReferenceSource,
  ) => {
    const selected = readSelectedTextInside(event.currentTarget);
    if (!selected) return;
    event.preventDefault();
    event.stopPropagation();
    const anchor = markState && source === "markdown_preview" && globalThis.CSS?.highlights
      ? previewAnchor(event.currentTarget, selected.range) : null;
    openTextReferenceMenu(
      {
        marks: anchor ? [anchor] : undefined,
        content: selected.content,
        contentMarkdown: renderedSelectionMarkdown(selected.range),
        pageNumber: source === "pdf" ? readPdfPage(selected.range) : undefined,
        documentFingerprint: source === "office"
          ? readDocumentFingerprint(event.currentTarget)
          : undefined,
        location: source === "office"
          ? readWordTextReferenceLocation(event.currentTarget, selected.range)
          : undefined,
        x: event.clientX,
        y: event.clientY,
      },
      source,
    );
  };

  const withTextReferenceMenu = (content: ReactNode) => (
    <>
      {content}
      {textReferenceMenu ? (
        <ContextMenu
          className="doc-editor__selection-menu"
          minWidth={104}
          withIcons
          onClose={() => setTextReferenceMenu(null)}
          position={{ x: textReferenceMenu.x, y: textReferenceMenu.y }}
        >
          <ContextMenuItem icon={<Copy size={14} />} onSelect={() => void copySelection(textReferenceMenu)}>
            {t("fileWorkspace.context.copy")}
          </ContextMenuItem>
          {markState && !!textReferenceMenu.marks?.length && (
            <ContextMenuItem icon={<Check size={14} />} onSelect={() => {
              void markState.change({ add: textReferenceMenu.marks });
              setTextReferenceMenu(null);
            }}>勾选</ContextMenuItem>
          )}
          {onCreateTextReference && textReferenceMenu.reference.content && (
            <ContextMenuItem
              icon={<ChatCircleText size={14} />}
              onSelect={() => {
                onCreateTextReference(textReferenceMenu.reference);
                setTextReferenceMenu(null);
              }}
            >
              {t("fileWorkspace.context.referenceToChat")}
            </ContextMenuItem>
          )}
          {textReferenceMenu.copyFailed && (
            <span className="doc-editor__selection-copy-error" role="alert">{t("projectOverview.copySessionFailed")}</span>
          )}
        </ContextMenu>
      ) : null}
    </>
  );

  return {
    handleRenderedTextContextMenu,
    handleSourceTextContextMenu,
    withTextReferenceMenu,
  };
}

function buildEditorTextReferenceDraft(
  tab: DocumentTab,
  selection: {
    content: string;
    contentMarkdown?: string;
    documentFingerprint?: string;
    endLine?: number;
    pageNumber?: number;
    location?: EditorWordTextReferenceLocation;
    source: EditorTextReferenceSource;
    startLine?: number;
  },
): EditorTextReferenceDraft {
  const filePath = getEditorDocumentPath(tab);
  return {
    content: selection.content,
    contentMarkdown: selection.contentMarkdown,
    displayPath: tab.displayPath,
    documentFingerprint: selection.documentFingerprint,
    endLine: selection.endLine,
    pageNumber: selection.pageNumber,
    fileName: tab.title,
    filePath,
    location: selection.location,
    projectId: tab.projectId,
    source: selection.source,
    startLine: selection.startLine,
  };
}

function readSelectedTextInside(surface: HTMLElement) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  if (!selection.anchorNode || !selection.focusNode) return null;
  if (!surface.contains(selection.anchorNode) || !surface.contains(selection.focusNode)) return null;
  const content = selection.toString();
  return content ? { content, range: selection.getRangeAt(0).cloneRange() } : null;
}

function readDocumentFingerprint(surface: HTMLElement) {
  return surface.querySelector<HTMLElement>("[data-document-fingerprint]")
    ?.dataset.documentFingerprint;
}

function readPdfPage(range: Range) {
  const node = range.startContainer;
  const element = node instanceof Element ? node : node.parentElement;
  const page = Number(element?.closest<HTMLElement>("[data-pdf-page]")?.dataset.pdfPage);
  return Number.isSafeInteger(page) && page > 0 ? page : undefined;
}
