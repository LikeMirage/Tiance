import type { EditorImageReference, EditorTextReference } from "./editorReference";

export type DocumentTextRevealTarget =
  | { type: "line_range"; start_line: number; end_line: number }
  | { type: "text"; text: string; occurrence?: number };

export type ToolDocumentRevealTarget =
  | { type: "pdf_page"; page: number }
  | DocumentTextRevealTarget
  | { type: "text_ranges"; ranges: DocumentTextRevealTarget[] };

export type DocumentRevealTarget = ToolDocumentRevealTarget
  | { type: "reference_text"; reference: EditorTextReference }
  | { type: "reference_image"; reference: EditorImageReference };

export type DocumentTextSelection = {
  type: "text_selection";
  start_line: number;
  end_line: number;
  start_column: number;
  end_column: number;
  from: number;
  to: number;
  source: "editor_buffer";
  match_count?: number;
  occurrence?: number;
};

export type DocumentTextRevealResult = DocumentTextSelection
  | { type: "text_selections"; ranges: DocumentTextSelection[]; source: "editor_buffer" };

export type DocumentRevealResult = DocumentTextRevealResult
  | { type: "pdf_page"; page: number; total_pages: number }
  | { type: "reference"; selected: boolean };

export class DocumentRevealError extends Error {
  constructor(public readonly code: string, message: string, public readonly details: Record<string, unknown> = {}) {
    super(message);
    this.name = "DocumentRevealError";
  }
}

export type DocumentRevealRequest = {
  target: DocumentRevealTarget;
  signal: AbortSignal;
  complete: (result: DocumentRevealResult) => void;
  fail: (error: unknown) => void;
};

/** Ephemeral UI command: completion means the renderer actually displayed the target. */
export function createDocumentRevealRequest(target: DocumentRevealTarget, signal: AbortSignal, timeoutMs = 30_000) {
  const controller = new AbortController();
  let settled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let resolve!: (result: DocumentRevealResult) => void;
  let reject!: (error: unknown) => void;
  const result = new Promise<DocumentRevealResult>((res, rej) => { resolve = res; reject = rej; });
  const cleanup = () => {
    settled = true;
    clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
    controller.abort();
  };
  const request: DocumentRevealRequest = {
    target,
    signal: controller.signal,
    complete(value) { if (!settled) { cleanup(); resolve(value); } },
    fail(error) { if (!settled) { cleanup(); reject(error); } },
  };
  const onAbort = () => request.fail(new DocumentRevealError("CANCELLED", "文件定位已取消。"));
  signal.addEventListener("abort", onAbort, { once: true });
  timer = setTimeout(() => request.fail(new DocumentRevealError(
    "REVEAL_TIMEOUT", "等待文件加载或定位完成超时；目标尚未确认显示。",
  )), timeoutMs);
  if (signal.aborted) onAbort();
  return { request, result };
}

export function parseDocumentRevealTarget(value: unknown): ToolDocumentRevealTarget {
  const invalid = () => new DocumentRevealError("INVALID_TARGET", "target 必须指定有效的 pdf_page、line_range、text 或 text_ranges 定位参数；页码、行号和 occurrence 从 1 开始。");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const target = value as Record<string, unknown>;
  const positive = (n: unknown): n is number => Number.isSafeInteger(n) && (n as number) > 0;
  const only = (...keys: string[]) => Object.keys(target).every((key) => keys.includes(key));
  if (target.type === "pdf_page" && positive(target.page) && only("type", "page")) {
    return { type: "pdf_page", page: target.page };
  }
  if (target.type === "text_ranges" && Array.isArray(target.ranges) && target.ranges.length > 0 && only("type", "ranges")) {
    const ranges = target.ranges.map((item, index) => {
      try {
        if (!item || (item.type !== "text" && item.type !== "line_range")) throw invalid();
        return parseDocumentRevealTarget(item) as DocumentTextRevealTarget;
      } catch (error) { throw withRangeIndex(error, index); }
    });
    return { type: "text_ranges", ranges };
  }
  if (target.type === "line_range" && positive(target.start_line) && positive(target.end_line)
    && target.end_line >= target.start_line && only("type", "start_line", "end_line")) {
    return { type: "line_range", start_line: target.start_line, end_line: target.end_line };
  }
  if (target.type === "text" && typeof target.text === "string" && target.text.length > 0
    && (target.occurrence === undefined || positive(target.occurrence)) && only("type", "text", "occurrence")) {
    return { type: "text", text: target.text, ...(target.occurrence === undefined ? {} : { occurrence: target.occurrence as number }) };
  }
  throw invalid();
}

type TextDocument = {
  lines: number;
  line: (number: number) => { from: number; to: number };
  lineAt: (position: number) => { number: number; from: number };
  toString: () => string;
};

export function resolveTextReveal(doc: TextDocument, target: DocumentTextRevealTarget, textContent?: string): DocumentTextSelection {
  let from: number;
  let to: number;
  let matchCount: number | undefined;
  if (target.type === "line_range") {
    if (target.end_line > doc.lines) throw new DocumentRevealError("LINE_OUT_OF_RANGE", `行号超出范围，当前文件共 ${doc.lines} 行。`, { total_lines: doc.lines });
    from = doc.line(target.start_line).from;
    to = doc.line(target.end_line).to;
  } else {
    // CodeMirror normalizes line endings, but whitespace and case remain exact.
    const needle = target.text.replace(/\r\n?/g, "\n");
    const content = textContent ?? doc.toString();
    matchCount = 0;
    from = -1;
    for (let offset = 0; offset <= content.length;) {
      const found = content.indexOf(needle, offset);
      if (found < 0) break;
      matchCount += 1;
      if (matchCount === (target.occurrence ?? 1)) from = found;
      offset = found + 1;
    }
    if (!matchCount) throw new DocumentRevealError("TEXT_NOT_FOUND", "指定内容在编辑器当前文本中不存在。");
    if (matchCount > 1 && target.occurrence === undefined) throw new DocumentRevealError("AMBIGUOUS_TEXT", `指定内容匹配到 ${matchCount} 处，请用 occurrence 指定第几处。`, { match_count: matchCount });
    if (from < 0) throw new DocumentRevealError("OCCURRENCE_OUT_OF_RANGE", `匹配次数超出范围，实际有 ${matchCount} 处。`, { match_count: matchCount });
    to = from + needle.length;
  }
  const start = doc.lineAt(from);
  const end = doc.lineAt(to);
  return {
    type: "text_selection", from, to,
    start_line: start.number, end_line: end.number,
    start_column: from - start.from + 1, end_column: to - end.from + 1,
    source: "editor_buffer",
    ...(matchCount === undefined ? {} : { match_count: matchCount, occurrence: target.type === "text" ? target.occurrence ?? 1 : undefined }),
  };
}

/** Resolve the entire request before changing the editor selection; never select a partial batch. */
export function resolveTextReveals(doc: TextDocument, target: Exclude<ToolDocumentRevealTarget, { type: "pdf_page" }>): DocumentTextRevealResult {
  if (target.type !== "text_ranges") return resolveTextReveal(doc, target);
  let content: string | undefined;
  const ranges = target.ranges.map((range, index) => {
    try {
      if (range.type === "text") content ??= doc.toString();
      return resolveTextReveal(doc, range, content);
    }
    catch (error) { throw withRangeIndex(error, index); }
  });
  return { type: "text_selections", ranges, source: "editor_buffer" };
}

export function resolveReferenceText(doc: TextDocument, reference: EditorTextReference): DocumentTextSelection {
  const needle = reference.content.replace(/\r\n?/g, "\n");
  if (!needle) throw new DocumentRevealError("TEXT_NOT_FOUND", "引用内容为空。");
  const content = doc.toString();
  // Stored line numbers are a hint, not permission to select unrelated, changed text.
  if (Number.isSafeInteger(reference.startLine) && Number.isSafeInteger(reference.endLine)
    && reference.startLine! > 0 && reference.endLine! >= reference.startLine! && reference.endLine! <= doc.lines) {
    const from = doc.line(reference.startLine!).from;
    const to = doc.line(reference.endLine!).to;
    const slice = content.slice(from, to);
    const offset = slice.indexOf(needle);
    if (offset >= 0 && slice.indexOf(needle, offset + 1) < 0) {
      const start = doc.lineAt(from + offset), end = doc.lineAt(from + offset + needle.length);
      return { type: "text_selection", from: from + offset, to: from + offset + needle.length,
        start_line: start.number, end_line: end.number, start_column: from + offset - start.from + 1,
        end_column: from + offset + needle.length - end.from + 1, source: "editor_buffer" };
    }
  }
  return resolveTextReveal(doc, { type: "text", text: needle }, content);
}

function withRangeIndex(error: unknown, index: number) {
  if (!(error instanceof DocumentRevealError)) return error;
  return new DocumentRevealError(error.code, `第 ${index + 1} 个范围：${error.message}`, {
    ...error.details, range_index: index + 1,
  });
}
