import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useDocumentReadingValue } from "../../../entities/editor/model/documentReadingState";
import { readWordChunk, type FilePreviewInspection } from "../../file-preview/model/filePreview";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type { OfficeLoadingVisibilityChange } from "./officePreviewTypes";
import { annotateWordChunk, paginateWordChunk, scheduleWordRender } from "./wordChunkLayout";
import { useDocumentRevealRequest } from "../../../entities/editor/model/documentRevealContext";
import { selectWordReference } from "./wordReferenceSelection";
import { DocumentRevealError, type DocumentRevealRequest } from "../../../entities/editor/model/documentReveal";

const ESTIMATED_HEIGHT = 1182;
type Anchor = { chunk: number; offset: number };

export function WordPreview({ inspection, onLoadingVisibleChange, onMissing, src, zoom }: {
  inspection: FilePreviewInspection;
  onLoadingVisibleChange?: OfficeLoadingVisibilityChange;
  onMissing?: (() => void) | null;
  src: string | null;
  zoom: number;
}) {
  const reveal = useDocumentRevealRequest();
  const [readyChunks, setReadyChunks] = useState<Set<number>>(() => new Set());
  const [pinnedChunks, setPinnedChunks] = useState<number[]>([]);
  const [pinnedRequest, setPinnedRequest] = useState<DocumentRevealRequest | null>(null);
  const count = inspection.word?.chunks ?? 0;
  const [savedAnchor, saveAnchor] = useDocumentReadingValue<Anchor>("word:anchor", { chunk: 0, offset: 0 });
  const anchor = useRef<Anchor>({ ...savedAnchor, chunk: Math.max(0, Math.min(savedAnchor.chunk, count - 1)) });
  const [center, setCenter] = useState(anchor.current.chunk);
  const [heights, setHeights] = useState<number[]>(() => Array(count).fill(ESTIMATED_HEIGHT));
  const [firstReady, setFirstReady] = useState(count === 0);
  const firstChunk = useRef(anchor.current.chunk);
  const scrollRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const restored = useRef(false);
  const onHeight = useCallback((index: number, height: number) => {
    setHeights(previous => previous[index] === height ? previous : previous.map((value, i) => i === index ? height : value));
  }, []);
  const onReady = useCallback((chunk: number) => {
    if (chunk === firstChunk.current) setFirstReady(true);
    setReadyChunks(current => new Set(current).add(chunk));
  }, []);
  const onUnmount = useCallback((chunk: number) => {
    setReadyChunks(current => { const next = new Set(current); next.delete(chunk); return next; });
  }, []);
  useEffect(() => {
    if (!reveal || reveal.signal.aborted || reveal.target.type !== "reference_text") return;
    const reference = reveal.target.reference;
    setPinnedRequest(null);
    const ranges = inspection.word?.ranges;
    const start = reference.location?.start.paragraphIndex, end = reference.location?.end.paragraphIndex;
    const first = start && ranges ? ranges.findIndex(([a, b]) => a != null && b != null && start >= a && start <= b) : -1;
    const last = end && ranges ? ranges.findIndex(([a, b]) => a != null && b != null && end >= a && end <= b) : -1;
    if (!reference.documentFingerprint || reference.documentFingerprint !== inspection.word?.fingerprint || first < 0 || last < first) {
      scrollRef.current?.ownerDocument.getSelection()?.removeAllRanges();
      setPinnedChunks([]);
      reveal.complete({ type: "reference", selected: false }); return;
    }
    setPinnedRequest(reveal);
    setPinnedChunks(Array.from({ length: last - first + 1 }, (_, index) => first + index));
    // A user scroll releases pinned content; cancellation does not tear down an active selection.
  }, [reveal, inspection.word]);
  useEffect(() => {
    if (!reveal || reveal.signal.aborted || reveal.target.type !== "reference_text"
      || pinnedRequest !== reveal || !pinnedChunks.length
      || !pinnedChunks.every(chunk => readyChunks.has(chunk)) || !scrollRef.current) return;
    const selected = selectWordReference(scrollRef.current, reveal.target.reference);
    if (selected) {
      // Persist the new reading anchor before later height measurements restore it.
      let offset = scrollRef.current.scrollTop / zoom, chunk = 0;
      while (chunk < heights.length - 1 && offset >= heights[chunk]) offset -= heights[chunk++];
      anchor.current = { chunk, offset }; saveAnchor(anchor.current); setCenter(chunk);
    }
    reveal.complete({ type: "reference", selected });
    if (!selected) setPinnedChunks([]);
  }, [reveal, pinnedRequest, pinnedChunks, readyChunks, zoom, heights, saveAnchor]);
  useEffect(() => { onLoadingVisibleChange?.(!firstReady); }, [firstReady, onLoadingVisibleChange]);
  useLayoutEffect(() => {
    if (!scrollRef.current) return;
    const top = heights.slice(0, anchor.current.chunk).reduce((sum, value) => sum + value, 0);
    const offset = Math.min(anchor.current.offset, Math.max(0, (heights[anchor.current.chunk] ?? ESTIMATED_HEIGHT) - 1));
    scrollRef.current.scrollTop = (top + offset) * zoom;
    restored.current = true;
  }, [heights, zoom]);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  const capture = () => {
    if (!scrollRef.current || !restored.current) return;
    let offset = scrollRef.current.scrollTop / zoom;
    let chunk = 0;
    while (chunk < heights.length - 1 && offset >= heights[chunk]) offset -= heights[chunk++];
    anchor.current = { chunk, offset };
    saveAnchor(anchor.current);
    setCenter(chunk);
  };
  return <main className="office-preview__body">
    {!firstReady && <LoadingStrip ariaLabel="正在加载 Word 文档" mode="fill" surface="dark" visual="ring" />}
    <div ref={scrollRef} className="office-preview__scroll office-preview__word-scroll" onWheel={() => {
      if (pinnedRequest && !pinnedRequest.signal.aborted) {
        pinnedRequest.fail(new DocumentRevealError("NAVIGATION_INTERRUPTED", "用户已滚动文档，定位中止。"));
      }
      setPinnedChunks([]);
    }} onScroll={() => {
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(capture);
    }}>
      <div className="office-preview__word" style={{ zoom }} data-document-fingerprint={inspection.word?.fingerprint}>
        {Array.from({ length: count }, (_, index) => <div key={index} data-word-chunk={index}
          style={Math.abs(index - center) <= 1 || pinnedChunks.includes(index) ? undefined : { height: heights[index] }}>
          {(Math.abs(index - center) <= 1 || pinnedChunks.includes(index)) && src && inspection.version
            ? <WordChunkView chunk={index} src={src} version={inspection.version}
                estimate={heights[index]} onHeight={onHeight} onReady={onReady} onUnmount={onUnmount} onMissing={onMissing} /> : null}
        </div>)}
      </div>
    </div>
  </main>;
}

function WordChunkView({ chunk, src, version, estimate, onHeight, onReady, onUnmount, onMissing }: {
  chunk: number; src: string; version: string; estimate: number;
  onHeight: (chunk: number, height: number) => void;
  onReady: (chunk: number) => void;
  onUnmount: (chunk: number) => void;
  onMissing?: (() => void) | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const onMissingRef = useRef(onMissing);
  onMissingRef.current = onMissing;
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const container = host.current!;
    container.replaceChildren();
    setState("loading");
    void (async () => {
      const data = await readWordChunk(src, version, chunk, signal);
      await scheduleWordRender(signal, async () => {
        const { renderAsync } = await import("docx-preview");
        signal.throwIfAborted();
        const prefix = `office-word-${chunk}-${crypto.randomUUID()}`;
        const staging = document.createElement("div");
        const bytes = Uint8Array.from(atob(data.package_base64), value => value.charCodeAt(0));
        const parsed = await renderAsync(bytes, staging, undefined, {
          className: prefix, inWrapper: true, breakPages: true,
          ignoreLastRenderedPageBreak: false, useBase64URL: true, renderAltChunks: false,
        });
        signal.throwIfAborted();
        annotateWordChunk(staging, data, prefix, parsed.numberingPart?.domNumberings);
        container.replaceChildren(staging);
        await paginateWordChunk(staging, prefix, signal);
        signal.throwIfAborted();
      });
      signal.throwIfAborted();
      setState("ready");
      onReady(chunk);
    })().catch((reason: unknown) => {
      if (signal.aborted) return;
      if (reason && typeof reason === "object" && "status" in reason && reason.status === 404) onMissingRef.current?.();
      container.replaceChildren();
      setError(reason instanceof Error ? reason.message : "Word 内容读取失败。");
      setState("error");
      onReady(chunk);
    });
    return () => { controller.abort(); container.replaceChildren(); onUnmount(chunk); };
  }, [chunk, src, version, attempt, onReady, onUnmount]);
  useLayoutEffect(() => {
    if (state !== "ready" || !host.current) return;
    const element = host.current;
    const measure = () => onHeight(chunk, Math.ceil(element.offsetHeight));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [state, chunk, onHeight]);
  return <div className="office-word-chunk" style={state === "ready" ? undefined : { height: estimate }}>
    {state === "loading" && <div className="office-word-chunk__placeholder" role="status">正在加载…</div>}
    {state === "error" && <div className="office-preview__status office-preview__status--error" role="alert">
      {error} <button onClick={() => setAttempt(value => value + 1)}>重试</button>
    </div>}
    <div ref={host} className={state === "ready" ? "office-word-chunk__content" : "office-word-chunk__measuring"} />
  </div>;
}
