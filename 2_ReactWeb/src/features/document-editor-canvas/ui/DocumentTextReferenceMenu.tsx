import { useEffect, useState } from "react";
import type { MouseEvent, ReactNode } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { getEditorDocumentPath } from "../../../entities/editor/model/editorWorkspaceFileReference";
import type {
  EditorTextReferenceDraft,
  EditorTextReferenceSource,
} from "../../../entities/editor/model/editorReference";
import { ContextMenu, ContextMenuItem } from "../../../shared/ui/context-menu";
import type { CodeEditorTextSelectionContextMenu } from "../../editor/ui/CodeEditor";

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
      endLine?: number;
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
        endLine: selection.endLine,
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
    const content = readSelectedTextInside(event.currentTarget);
    if (!content) return;
    event.preventDefault();
    event.stopPropagation();
    openTextReferenceMenu(
      {
        content,
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
    endLine?: number;
    source: EditorTextReferenceSource;
    startLine?: number;
  },
): EditorTextReferenceDraft {
  const filePath = getEditorDocumentPath(tab);
  return {
    content: selection.content,
    displayPath: tab.displayPath,
    endLine: selection.endLine,
    fileName: tab.title,
    filePath,
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
  return content || null;
}
