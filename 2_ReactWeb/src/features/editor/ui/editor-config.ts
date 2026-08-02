import { closeBrackets, autocompletion } from "@codemirror/autocomplete";
import { history, historyKeymap } from "@codemirror/commands";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { bracketMatching, indentOnInput } from "@codemirror/language";
import { highlightSelectionMatches } from "@codemirror/search";
import { EditorState, type Extension } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  rectangularSelection,
} from "@codemirror/view";

import type { DocumentLanguage } from "../../../entities/editor/model/editorDocument";
import { editorTheme } from "./editor-theme";

type EditorConfigOptions = {
  readOnly?: boolean;
  onSave?: () => void;
};

const languageExtensions: Record<DocumentLanguage, () => Extension> = {
  javascript,
  typescript: javascript,
  python,
  html: () => html(),
  css,
  json,
  markdown: () => markdown(),
  plaintext: () => [],
};

export function createEditorExtensions(
  languageId: DocumentLanguage,
  options: EditorConfigOptions = {},
): Extension[] {
  const langFn = languageExtensions[languageId] || languageExtensions.plaintext;
  const saveKey = keymap.of([
    {
      key: "Mod-s",
      run: (view) => {
        options.onSave?.();
        return true;
      },
      preventDefault: true,
    },
  ]);

  const exts: Extension[] = [
    lineNumbers(),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    drawSelection(),
    rectangularSelection(),
    bracketMatching(),
    closeBrackets(),
    indentOnInput(),
    highlightSelectionMatches(),
    history(),
    keymap.of(historyKeymap),
    editorTheme,
    langFn(),
    saveKey,
    EditorView.lineWrapping,
    EditorState.tabSize.of(2),
  ];

  if (options.readOnly) {
    exts.push(EditorState.readOnly.of(true));
    exts.push(EditorView.editable.of(false));
  }

  return exts;
}
