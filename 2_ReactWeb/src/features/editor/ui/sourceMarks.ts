import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, type DecorationSet } from "@codemirror/view";
import type { DocumentMark } from "../model/documentMarks";
import { resolveMark } from "../model/documentMarks";

export const setSourceMarks = StateEffect.define<DecorationSet>();
export const sourceMarksField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    for (const effect of transaction.effects) if (effect.is(setSourceMarks)) return effect.value;
    return value.map(transaction.changes);
  },
  provide: field => EditorView.decorations.from(field),
});

class CancelMark extends WidgetType {
  constructor(readonly id: string, readonly remove: (id: string) => void) { super(); }
  eq(other: CancelMark) { return other.id === this.id && other.remove === this.remove; }
  toDOM() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "document-mark-cancel";
    button.textContent = "取消勾选";
    button.onmousedown = event => event.preventDefault();
    button.onclick = () => this.remove(this.id);
    return button;
  }
}

export function sourceMarkDecorations(view: EditorView, marks: DocumentMark[], remove: (id: string) => void) {
  if (!marks.some(mark => mark.surface === "source") && !view.state.field(sourceMarksField).size) return [];
  const text = view.state.doc.toString();
  const missing = [];
  const decorations = [];
  for (const mark of marks) {
    if (mark.surface !== "source") continue;
    const range = resolveMark(text, mark);
    if (!range) { missing.push(mark.id); continue; }
    const corner = Math.min(range.to, view.state.doc.lineAt(range.from).to);
    decorations.push(Decoration.mark({ class: "document-mark-text" }).range(range.from, range.to),
      Decoration.widget({ widget: new CancelMark(mark.id, remove), side: 1 }).range(corner));
  }
  view.dispatch({ effects: setSourceMarks.of(Decoration.set(decorations, true)) });
  return missing;
}
