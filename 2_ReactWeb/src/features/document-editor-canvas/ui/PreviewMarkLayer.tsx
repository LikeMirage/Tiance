import { useEffect, useState, type RefObject } from "react";
import { useDocumentMarks } from "../../editor/model/DocumentMarksContext";
import { resolveMark } from "../../editor/model/documentMarks";
import { indexPreview, previewRange } from "../model/previewMarkText";
import "../../editor/ui/documentMarks.css";

const highlightName = "tiance-document-marks";
const owners = new Map<HTMLElement, Range[]>();
function paint(owner: HTMLElement, ranges: Range[]) {
  if (ranges.length) owners.set(owner, ranges); else owners.delete(owner);
  if (!owners.size) { CSS.highlights.delete(highlightName); return; }
  const highlight = new Highlight();
  for (const collection of owners.values()) for (const range of collection) highlight.add(range);
  CSS.highlights.set(highlightName, highlight);
}

type Row = { top: number; right: number; ids: string[] };
export function PreviewMarkLayer({ scroller }: { scroller: RefObject<HTMLDivElement | null> }) {
  const state = useDocumentMarks();
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    const owner = scroller.current;
    const body = owner?.querySelector<HTMLElement>(".document-mark-preview-body");
    const marks = state?.marks.filter(mark => mark.surface === "preview");
    if (!owner || !body || !state || !marks?.length || !globalThis.CSS?.highlights) {
      setRows([]); return;
    }
    const ranges = new Map<string, Range>();
    let frame = 0, dirty = true;
    const removed = new Set<string>();
    function schedule(reindex = false) {
      dirty ||= reindex;
      if (!frame) frame = requestAnimationFrame(render);
    }
    function render() {
      frame = 0;
      const root = body!.querySelector(".markdown-preview--progressive");
      if (!root) return;
      if (dirty) {
        dirty = false;
        ranges.clear();
        const { text, spans } = indexPreview(root);
        const missing = [];
        for (const mark of marks!) {
          const found = resolveMark(text, mark);
          const range = found && previewRange(spans, found.from, found.to);
          if (range) ranges.set(mark.id, range);
          else if (state!.saved && root.getAttribute("aria-busy") === "false" && !removed.has(mark.id)) {
            missing.push(mark.id); removed.add(mark.id);
          }
        }
        paint(owner!, [...ranges.values()]);
        if (missing.length) void state!.change({ remove: missing });
      }
      const box = owner!.getBoundingClientRect(), groups: Row[] = [];
      for (const [id, range] of ranges) {
        const rects = range.getClientRects();
        const rect = rects[0];
        if (!rect) continue;
        let firstLineRight = rect.right;
        for (const fragment of rects) {
          if (fragment.top >= rect.bottom) break;
          firstLineRight = Math.max(firstLineRight, fragment.right);
        }
        const top = Math.max(0, Math.round(rect.top - box.top + owner!.scrollTop - 18));
        const right = Math.max(6, owner!.clientWidth - Math.max(70, firstLineRight - box.left + owner!.scrollLeft));
        const group = groups.find(item => Math.abs(item.top - top) <= 3);
        if (group) { group.ids.push(id); group.right = Math.min(group.right, right); }
        else groups.push({ top, right, ids: [id] });
      }
      setRows(groups);
    }
    const mutations = new MutationObserver(() => schedule(true));
    mutations.observe(body, { subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ["aria-busy"] });
    const resize = new ResizeObserver(() => schedule());
    resize.observe(owner); resize.observe(body);
    const onLoad = () => schedule();
    body.addEventListener("load", onLoad, true);
    schedule();
    return () => {
      mutations.disconnect(); resize.disconnect(); cancelAnimationFrame(frame);
      body.removeEventListener("load", onLoad, true);
      paint(owner, []);
    };
  }, [state, scroller]);
  return <>{rows.map(row => <div key={row.ids[0]} className="document-mark-controls"
    style={{ top: row.top, right: row.right }}>
    {row.ids.map(id => <button type="button" key={id} className="document-mark-cancel"
      onClick={() => void state?.change({ remove: [id] })}>取消勾选</button>)}
  </div>)}</>;
}
