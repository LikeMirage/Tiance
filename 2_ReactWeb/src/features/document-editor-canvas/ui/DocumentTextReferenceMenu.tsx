import { useEffect, useState } from "react";
import type { MouseEvent, ReactNode } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { getEditorDocumentPath } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorTextReferenceDraft,
  EditorTextReferenceSource,
  EditorWordTextReferenceLocation,
} from "../../../entities/editor/model/editorReference";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import type { CodeEditorTextSelectionContextMenu } from "../../editor/ui/CodeEditor";
import { readWordTextReferenceLocation } from "../model/wordTextReferenceLocation";
import { renderedSelectionMarkdown } from "../model/renderedSelectionMarkdown";

type TextReferenceMenuState = {
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
  const [textReferenceMenu, setTextReferenceMenu] = useState<TextReferenceMenuState>(null);

  useEffect(() => {
    setTextReferenceMenu(null);
  }, [activeTab?.id]);

  const openTextReferenceMenu = (
    selection: {
      content: string;
      contentMarkdown?: string;
      documentFingerprint?: string;
      endLine?: number;
      location?: EditorWordTextReferenceLocation;
      startLine?: number;
      x: number;
      y: number;
    },
    source: EditorTextReferenceSource,
  ) => {
    if (!activeTab || !onCreateTextReference) return;
    const content = selection.content.trim();
    if (!content) return;
    setTextReferenceMenu({
      reference: buildEditorTextReferenceDraft(activeTab, {
        content,
        contentMarkdown: selection.contentMarkdown,
        documentFingerprint: selection.documentFingerprint,
        endLine: selection.endLine,
        location: selection.location,
        source,
        startLine: selection.startLine,
      }),
      x: selection.x,
      y: selection.y,
    });
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
    openTextReferenceMenu(
      {
        content: selected.content,
        contentMarkdown: renderedSelectionMarkdown(selected.range),
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
          onClose={() => setTextReferenceMenu(null)}
          position={{ x: textReferenceMenu.x, y: textReferenceMenu.y }}
        >
          <ContextMenuItem
            onSelect={() => {
              onCreateTextReference?.(textReferenceMenu.reference);
              setTextReferenceMenu(null);
            }}
          >
            引用到对话
          </ContextMenuItem>
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
  const content = selection.toString().trim();
  return content ? { content, range: selection.getRangeAt(0).cloneRange() } : null;
}

function readDocumentFingerprint(surface: HTMLElement) {
  return surface.querySelector<HTMLElement>("[data-document-fingerprint]")
    ?.dataset.documentFingerprint;
}
