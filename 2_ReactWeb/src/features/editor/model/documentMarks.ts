export type DocumentMark = {
  id: string;
  surface: "source" | "preview";
  start: number;
  length: number;
  startLine: number;
  endLine: number;
  head: string;
  tail: string;
  before: string;
  after: string;
  digest: string;
};

export type MarkRange = { from: number; to: number };

function fingerprint(text: string, from: number, to: number) {
  let a = 2166136261, b = 5381;
  for (let index = from; index < to; index++) {
    const unit = text.charCodeAt(index);
    a = Math.imul(a ^ unit, 16777619);
    b = Math.imul(b, 33) ^ unit;
  }
  return [a, b].map(value => (value >>> 0).toString(16).padStart(8, "0")).join("");
}

// Never serialize half of a UTF-16 surrogate at an excerpt boundary.
function excerpt(text: string) {
  return text.replace(/^[\uDC00-\uDFFF]|[\uD800-\uDBFF]$/g, "");
}

export function anchorSelection(text: string, range: MarkRange, surface: DocumentMark["surface"]): DocumentMark {
  const { from, to } = range;
  if (from < 0 || to <= from || to > text.length) throw Error("选区已变化，请重新选择。");
  let startLine = 1, endLine = 1;
  for (let index = 0; index < to; index++) {
    if (text.charCodeAt(index) !== 10) continue;
    if (index < from) startLine++;
    endLine++;
  }
  // getRandomValues is available in both the desktop shell and HTTP LAN sessions.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  const id = [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
  return { id, surface, start: from, length: to - from, startLine, endLine,
    head: excerpt(text.slice(from, Math.min(to, from + 48))),
    tail: excerpt(text.slice(Math.max(from, to - 48), to)),
    before: excerpt(text.slice(Math.max(0, from - 32), from)),
    after: excerpt(text.slice(to, to + 32)), digest: fingerprint(text, from, to) };
}

export function resolveMark(text: string, mark: DocumentMark): MarkRange | null {
  const { start, length, head, tail, before, after, digest } = mark;
  const matches = (at: number) => at + length <= text.length && text.startsWith(head, at)
    && text.startsWith(tail, at + length - tail.length) && fingerprint(text, at, at + length) === digest;
  const contextScore = (at: number) => {
    let left = 0, right = 0;
    while (left < before.length && before[before.length - 1 - left] === text[at - 1 - left]) left++;
    while (right < after.length && after[right] === text[at + length + right]) right++;
    return left + right;
  };
  if (matches(start) && contextScore(start) === before.length + after.length) {
    return { from: start, to: start + length };
  }
  if (!head) return null;
  let best = -1, bestScore = -1;
  for (let at = text.indexOf(head); at !== -1; at = text.indexOf(head, at + 1)) {
    const score = contextScore(at);
    if (score < bestScore || (score === bestScore && Math.abs(at - start) >= Math.abs(best - start))) continue;
    if (matches(at)) { best = at; bestScore = score; }
  }
  return best < 0 ? null : { from: best, to: best + length };
}
