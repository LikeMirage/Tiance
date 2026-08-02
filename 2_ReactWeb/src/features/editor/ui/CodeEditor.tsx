import { Compartment, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { useEffect, useRef } from "react";

import type { DocumentLanguage } from "../../../entities/editor/model/editorDocument";
import { createEditorExtensions } from "./editor-config";
import "./editor.css";

export type CodeEditorTextSelectionContextMenu = {
  content: string;
  endLine: number;
  startLine: number;
  x: number;
  y: number;
};

type CodeEditorProps = {
  languageId: DocumentLanguage;
  onChange: (value: string) => void;
  onDirty?: () => void;
  onSave?: (value: string) => void;
  onScrollerReady?: (scroller: HTMLElement | null) => void;
  onScroll?: (scroller: HTMLElement) => void;
  onTextSelectionContextMenu?: (selection: CodeEditorTextSelectionContextMenu) => void;
  readOnly?: boolean;
  value: string;
};

const CHANGE_COMMIT_DELAY_MS = 220;

export function CodeEditor({
  value,
  languageId,
  onChange,
  onDirty,
  onSave,
  onScrollerReady,
  onScroll,
  onTextSelectionContextMenu,
  readOnly,
}: CodeEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onDirtyRef = useRef(onDirty);
  const onSaveRef = useRef(onSave);
  const onScrollerReadyRef = useRef(onScrollerReady);
  const onScrollRef = useRef(onScroll);
  const onTextSelectionContextMenuRef = useRef(onTextSelectionContextMenu);
  const langCompartmentRef = useRef(new Compartment());
  const pendingChangeTimerRef = useRef<number | null>(null);
  const lastCommittedValueRef = useRef(value);
  const applyingExternalValueRef = useRef(false);

  onChangeRef.current = onChange;
  onDirtyRef.current = onDirty;
  onSaveRef.current = onSave;
  onScrollerReadyRef.current = onScrollerReady;
  onScrollRef.current = onScroll;
  onTextSelectionContextMenuRef.current = onTextSelectionContextMenu;

  const flushPendingChange = () => {
    const view = viewRef.current;
    const hadPendingChange = pendingChangeTimerRef.current !== null;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
      pendingChangeTimerRef.current = null;
    }
    if (!view) return lastCommittedValueRef.current;

    const nextValue = view.state.doc.toString();
    if (hadPendingChange || nextValue !== lastCommittedValueRef.current) {
      lastCommittedValueRef.current = nextValue;
      onChangeRef.current(nextValue);
    }
    return nextValue;
  };

  const scheduleChangeCommit = () => {
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
    }
    pendingChangeTimerRef.current = window.setTimeout(() => {
      flushPendingChange();
    }, CHANGE_COMMIT_DELAY_MS);
  };

  const saveCurrentDocument = () => {
    const nextValue = flushPendingChange();
    onSaveRef.current?.(nextValue);
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        if (applyingExternalValueRef.current) return;
        onDirtyRef.current?.();
        scheduleChangeCommit();
      }
    });

    const state = EditorState.create({
      doc: value,
      extensions: [
        langCompartmentRef.current.of(createEditorExtensions(languageId, { readOnly, onSave: saveCurrentDocument })),
        updateListener,
      ],
    });

    const view = new EditorView({ state, parent: container });
    viewRef.current = view;
    onScrollerReadyRef.current?.(view.scrollDOM);

    const handleScroll = () => onScrollRef.current?.(view.scrollDOM);
    const handleContextMenu = (event: MouseEvent) => {
      const selectionHandler = onTextSelectionContextMenuRef.current;
      if (!selectionHandler) return;
      const selectedRanges = view.state.selection.ranges.filter((range) => !range.empty);
      if (selectedRanges.length === 0) return;

      const from = Math.min(...selectedRanges.map((range) => range.from));
      const to = Math.max(...selectedRanges.map((range) => range.to));
      const content = selectedRanges
        .map((range) => view.state.sliceDoc(range.from, range.to))
        .join("\n")
        .trim();
      if (!content) return;

      event.preventDefault();
      event.stopPropagation();
      selectionHandler({
        content,
        endLine: view.state.doc.lineAt(to).number,
        startLine: view.state.doc.lineAt(from).number,
        x: event.clientX,
        y: event.clientY,
      });
    };
    const handleBlur = () => {
      if (pendingChangeTimerRef.current !== null) {
        flushPendingChange();
      }
    };
    view.scrollDOM.addEventListener("scroll", handleScroll, { passive: true });
    view.dom.addEventListener("contextmenu", handleContextMenu);
    view.contentDOM.addEventListener("blur", handleBlur, true);

    return () => {
      if (pendingChangeTimerRef.current !== null) {
        flushPendingChange();
      }
      view.scrollDOM.removeEventListener("scroll", handleScroll);
      view.dom.removeEventListener("contextmenu", handleContextMenu);
      view.contentDOM.removeEventListener("blur", handleBlur, true);
      onScrollerReadyRef.current?.(null);
      view.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync external value changes (tab switching, file loading)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const committedValue =
      pendingChangeTimerRef.current !== null ? flushPendingChange() : lastCommittedValueRef.current;
    if (value !== committedValue) {
      applyingExternalValueRef.current = true;
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: value },
      });
      applyingExternalValueRef.current = false;
      lastCommittedValueRef.current = value;
    }
  }, [value]);

  // Sync language / readOnly changes
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: langCompartmentRef.current.reconfigure(
        createEditorExtensions(languageId, { readOnly, onSave: saveCurrentDocument }),
      ),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [languageId, readOnly]);

  return <div ref={containerRef} className="code-editor" />;
}
