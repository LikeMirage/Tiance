import { EditorSelection, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, layer, RectangleMarker, type DecorationSet, type LayerMarker } from "@codemirror/view";
import type { DocumentMark } from "../model/documentMarks";
import { resolveMark } from "../model/documentMarks";

export const setSourceMarks = StateEffect.define<DecorationSet>();
const selectedText = Decoration.mark({ class: "document-mark-text" });
type MarkControl = { id: string; remove: (id: string) => void };

class MarkControlRow implements LayerMarker {
  constructor(readonly top: number, readonly left: number, readonly width: number,
    public anchor: number, readonly controls: MarkControl[]) {}

  eq(other: MarkControlRow) {
    return this.top === other.top && this.left === other.left && this.width === other.width
      && this.anchor === other.anchor && this.controls.length === other.controls.length
      && this.controls.every((control, i) => control.id === other.controls[i].id && control.remove === other.controls[i].remove);
  }

  draw() {
    const row = document.createElement("div");
    row.className = "document-mark-source-row";
    row.style.top = `${this.top}px`;
    row.style.left = `${this.left}px`;
    row.style.width = `${this.width}px`;
    row.style.setProperty("--mark-end", `${this.anchor - this.left}px`);
    const group = document.createElement("div");
    group.className = "document-mark-source-buttons";
    for (const { id, remove } of this.controls) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "document-mark-cancel";
      button.textContent = "取消勾选";
      button.onmousedown = event => event.preventDefault();
      button.onclick = () => remove(id);
      group.appendChild(button);
    }
    row.appendChild(group);
    return row;
  }
}

export const sourceMarksField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    for (const effect of transaction.effects) if (effect.is(setSourceMarks)) return effect.value;
    return value.map(transaction.changes);
  },
  provide: field => [
    EditorView.decorations.from(field),
    // CodeMirror keeps its selection when the native DOM selection loses focus.
    EditorView.decorations.compute(["selection"], state => Decoration.set(
      state.selection.ranges.filter(range => !range.empty).map(range => selectedText.range(range.from, range.to)),
    )),
    EditorView.editorAttributes.from(field, marks => ({ class: marks.size ? "cm-has-document-marks" : "" })),
    layer({
      above: false,
      class: "cm-documentMarkLayer",
      update: update => update.selectionSet || update.viewportChanged || update.docChanged
        || update.startState.field(field) !== update.state.field(field),
      markers(view) {
        const marks = view.state.field(field);
        if (!marks.size) return [];
        const ranges = view.state.selection.ranges.filter(range => !range.empty);
        marks.between(view.viewport.from, view.viewport.to, (from, to) => {
          ranges.push(EditorSelection.range(from, to));
        });
        if (!ranges.length) return [];
        // Merge only for painting. Each saved mark keeps its own ID and cancel button.
        return EditorSelection.create(ranges).ranges.flatMap(range =>
          RectangleMarker.forRange(view, "cm-documentMarkBackground", range));
      },
    }),
    layer({
      above: true,
      class: "cm-documentMarkControls",
      mount: element => element.removeAttribute("aria-hidden"),
      update: update => update.viewportChanged || update.docChanged || update.startState.field(field) !== update.state.field(field),
      markers(view) {
        const marks = view.state.field(field);
        if (!marks.size) return [];
        const content = view.contentDOM.getBoundingClientRect();
        const scroller = view.scrollDOM.getBoundingClientRect();
        const left = content.left - scroller.left + view.scrollDOM.scrollLeft * view.scaleX;
        const rows = new Map<number, MarkControlRow>();
        marks.between(view.viewport.from, view.viewport.to, (from, to, mark) => {
          if (from < view.viewport.from) return;
          const rects = RectangleMarker.forRange(view, "", EditorSelection.range(from, to));
          if (!rects.length) return;
          const top = Math.round(rects[0].top);
          const anchor = Math.max(...rects.filter(rect => Math.round(rect.top) === top)
            .map(rect => rect.left + (rect.width ?? 0))) + 2;
          const row = rows.get(top) ?? new MarkControlRow(top, left, content.width, anchor, []);
          row.anchor = Math.max(row.anchor, anchor);
          row.controls.push(mark.spec.control);
          rows.set(top, row);
        });
        return [...rows.values()];
      },
    }),
  ],
});

export function sourceMarkDecorations(view: EditorView, marks: DocumentMark[], remove: (id: string) => void) {
  if (!marks.some(mark => mark.surface === "source") && !view.state.field(sourceMarksField).size) return [];
  const text = view.state.doc.toString();
  const missing = [];
  const decorations = [];
  for (const mark of marks) {
    if (mark.surface !== "source") continue;
    const range = resolveMark(text, mark);
    if (!range) { missing.push(mark.id); continue; }
    decorations.push(Decoration.mark({
      class: "document-mark-text",
      control: { id: mark.id, remove } satisfies MarkControl,
    }).range(range.from, range.to));
  }
  view.dispatch({ effects: setSourceMarks.of(Decoration.set(decorations, true)) });
  return missing;
}
