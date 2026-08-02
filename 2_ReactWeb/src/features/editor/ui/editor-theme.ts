import { EditorView } from "@codemirror/view";

export const editorTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "var(--editor-background)",
      color: "var(--editor-foreground)",
      fontSize: "13px",
      fontFamily: '"Consolas", "Courier New", monospace',
      height: "100%",
    },
    ".cm-content": {
      caretColor: "var(--color-accent)",
      padding: "0 8px",
      fontFamily: "inherit",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--color-accent)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "var(--color-text-selection-bg)",
    },
    ".cm-content ::selection": {
      color: "var(--color-text-selection-text)",
    },
    ".cm-activeLine": { backgroundColor: "var(--editor-active-line)" },
    ".cm-selectionMatch": { backgroundColor: "var(--editor-selection-match)" },
    ".cm-gutters": {
      backgroundColor: "var(--editor-gutter-background)",
      color: "var(--editor-gutter-foreground)",
      border: "none",
      paddingRight: "2px",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "var(--editor-active-line)",
      color: "var(--color-text-secondary)",
    },
    ".cm-foldPlaceholder": {
      backgroundColor: "var(--color-surface-muted)",
      color: "var(--color-text-secondary)",
      border: "1px solid var(--color-border-soft)",
    },
    ".cm-matchingBracket": { backgroundColor: "var(--color-selection-accent-bg)", outline: "none" },
    ".cm-nonmatchingBracket": { backgroundColor: "var(--color-danger-bg)" },
    ".cm-tooltip": {
      backgroundColor: "var(--editor-tooltip-background)",
      border: "1px solid var(--color-border-soft)",
      color: "var(--editor-foreground)",
    },
    ".cm-tooltip-autocomplete": {
      "& li[aria-selected]": { backgroundColor: "var(--color-selection-accent-bg-hover)" },
    },
  },
);
