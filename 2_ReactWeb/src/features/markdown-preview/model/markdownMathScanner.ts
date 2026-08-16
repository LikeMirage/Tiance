export type MarkdownMathRange = {
  bodyEnd: number;
  bodyStart: number;
  closed: boolean;
  delimiter: "$" | "$$" | "\\(" | "\\[" | "environment";
  displayMode: boolean;
  end: number;
  start: number;
};

type TextRange = { end: number; start: number };

const DISPLAY_ENVIRONMENTS = new Set([
  "CD",
  "align",
  "align*",
  "aligned",
  "alignedat",
  "alignat",
  "alignat*",
  "array",
  "bmatrix",
  "cases",
  "eqnarray",
  "eqnarray*",
  "equation",
  "equation*",
  "gather",
  "gather*",
  "gathered",
  "matrix",
  "pmatrix",
  "smallmatrix",
  "split",
  "vmatrix",
  "Vmatrix",
]);

const HTML_TAG_NAMES = new Set([
  "a",
  "abbr",
  "address",
  "article",
  "aside",
  "audio",
  "b",
  "body",
  "blockquote",
  "br",
  "caption",
  "center",
  "cite",
  "code",
  "col",
  "colgroup",
  "dd",
  "del",
  "details",
  "div",
  "dl",
  "dt",
  "em",
  "figcaption",
  "figure",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "head",
  "hr",
  "html",
  "i",
  "img",
  "iframe",
  "ins",
  "kbd",
  "label",
  "li",
  "link",
  "main",
  "mark",
  "meta",
  "nav",
  "ol",
  "p",
  "picture",
  "pre",
  "q",
  "s",
  "samp",
  "script",
  "section",
  "select",
  "small",
  "source",
  "span",
  "strong",
  "style",
  "sub",
  "summary",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "textarea",
  "time",
  "tr",
  "u",
  "ul",
  "var",
  "video",
  "wbr",
  "button",
  "input",
  "option",
]);

export function findMarkdownMathRanges(content: string): MarkdownMathRange[] {
  if (!content) return [];
  const protectedRanges = collectProtectedMarkdownRanges(content);
  const ranges = findDelimitedMathRanges(content, protectedRanges);
  ranges.push(...findStandaloneEnvironmentRanges(content, protectedRanges, ranges));
  return ranges.sort((left, right) => left.start - right.start);
}

/**
 * Finds the formula that is still growing at the end of a streaming Markdown
 * fragment. Display formulas are already part of the normal scan; unfinished
 * inline formulas are detected separately so ordinary completed-document
 * dollar text keeps its existing interpretation.
 */
export function findPendingMarkdownMathRange(
  content: string,
): MarkdownMathRange | null {
  if (!content) return null;
  const protectedRanges = collectProtectedMarkdownRanges(content);
  const ranges = findDelimitedMathRanges(content, protectedRanges);
  ranges.push(...findStandaloneEnvironmentRanges(content, protectedRanges, ranges));
  ranges.sort((left, right) => left.start - right.start);

  const pendingDisplayRange = ranges.find((range) => !range.closed);
  if (pendingDisplayRange) return pendingDisplayRange;

  return findPendingInlineMathRange(content, protectedRanges, ranges);
}

export function escapeAmbiguousMarkdownDollars(content: string) {
  if (!content.includes("$")) return content;
  const protectedRanges = collectProtectedMarkdownRanges(content);
  const mathRanges = findMarkdownMathRanges(content);
  const preservedRanges = mergeTextRanges([
    ...protectedRanges,
    ...mathRanges.map((range) => ({ start: range.start, end: range.end })),
  ]);
  let output = "";
  let cursor = 0;
  let rangeIndex = 0;
  while (cursor < content.length) {
    const range = preservedRanges[rangeIndex];
    if (range && cursor >= range.end) {
      rangeIndex += 1;
      continue;
    }
    if (range && cursor >= range.start) {
      output += content.slice(cursor, range.end);
      cursor = range.end;
      rangeIndex += 1;
      continue;
    }
    const nextBoundary = range?.start ?? content.length;
    const text = content.slice(cursor, nextBoundary);
    output += escapeDollarText(text);
    cursor = nextBoundary;
  }
  return output;
}

function escapeDollarText(text: string) {
  let output = "";
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "$" && !isEscaped(text, index)) output += "\\";
    output += text[index];
  }
  return output;
}

export function isOffsetInsideMathRange(
  offset: number,
  ranges: readonly MarkdownMathRange[],
) {
  let low = 0;
  let high = ranges.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const range = ranges[middle];
    if (offset <= range.start) {
      high = middle - 1;
    } else if (offset >= range.end) {
      low = middle + 1;
    } else {
      return true;
    }
  }
  return false;
}

function findDelimitedMathRanges(content: string, protectedRanges: TextRange[]) {
  const ranges: MarkdownMathRange[] = [];
  let cursor = 0;
  let protectedIndex = 0;

  while (cursor < content.length) {
    while (
      protectedIndex < protectedRanges.length
      && cursor >= protectedRanges[protectedIndex].end
    ) {
      protectedIndex += 1;
    }
    const protectedRange = protectedRanges[protectedIndex];
    if (protectedRange && cursor >= protectedRange.start) {
      cursor = protectedRange.end;
      continue;
    }

    const opener = readMathOpener(content, cursor);
    if (!opener) {
      cursor += 1;
      continue;
    }

    const bodyStart = cursor + opener.open.length;
    const closeStart = findMathCloser(
      content,
      bodyStart,
      opener.close,
      protectedRanges,
      opener.open === "$" || opener.open === "\\(",
    );
    const closed = closeStart >= 0;
    if (!closed && (opener.open === "$" || opener.open === "\\(")) {
      cursor += opener.open.length;
      continue;
    }
    const bodyEnd = closed ? closeStart : content.length;
    const end = closed ? closeStart + opener.close.length : content.length;
    if (
      opener.open === "$"
      && closed
      && !isInlineDollarMathCandidate(content, cursor, bodyStart, bodyEnd, end)
    ) {
      cursor += 1;
      continue;
    }

    ranges.push({
      bodyEnd,
      bodyStart,
      closed,
      delimiter: opener.open,
      displayMode: opener.open !== "$" && opener.open !== "\\(",
      end,
      start: cursor,
    });
    cursor = Math.max(cursor + 1, end);
  }
  return ranges;
}

function findPendingInlineMathRange(
  content: string,
  protectedRanges: TextRange[],
  existingRanges: MarkdownMathRange[],
): MarkdownMathRange | null {
  const excludedRanges = mergeTextRanges([
    ...protectedRanges,
    ...existingRanges.map((range) => ({ start: range.start, end: range.end })),
  ]);
  let cursor = 0;

  while (cursor < content.length) {
    const excludedRange = excludedRanges.find((range) => (
      cursor >= range.start && cursor < range.end
    ));
    if (excludedRange) {
      cursor = excludedRange.end;
      continue;
    }

    const opener = readMathOpener(content, cursor);
    if (!opener || (opener.open !== "$" && opener.open !== "\\(")) {
      cursor += 1;
      continue;
    }

    const bodyStart = cursor + opener.open.length;
    const closeStart = findMathCloser(
      content,
      bodyStart,
      opener.close,
      excludedRanges,
      true,
    );
    if (closeStart >= 0) {
      cursor = closeStart + opener.close.length;
      continue;
    }

    const nextKnownRange = existingRanges.find((range) => range.start > cursor);
    if (nextKnownRange) {
      cursor = nextKnownRange.end;
      continue;
    }

    const body = content.slice(bodyStart);
    if (/\r|\n/.test(body) || !body.trim()) return null;
    if (opener.open === "$" && /^\d+(?:[.,]\d{0,2})?(?:\s|$)/.test(body)) {
      return null;
    }

    return {
      bodyEnd: content.length,
      bodyStart,
      closed: false,
      delimiter: opener.open,
      displayMode: false,
      end: content.length,
      start: cursor,
    };
  }

  return null;
}

function readMathOpener(content: string, index: number) {
  if (isEscaped(content, index)) return null;
  if (content.startsWith("$$", index)) {
    return { close: "$$", open: "$$" as const };
  }
  if (content.startsWith("\\[", index)) {
    return { close: "\\]", open: "\\[" as const };
  }
  if (content.startsWith("\\(", index)) {
    return { close: "\\)", open: "\\(" as const };
  }
  if (
    content[index] === "$"
    && content[index - 1] !== "$"
    && content[index + 1] !== "$"
  ) {
    return { close: "$", open: "$" as const };
  }
  return null;
}

function findMathCloser(
  content: string,
  start: number,
  delimiter: string,
  protectedRanges: TextRange[],
  singleLine: boolean,
) {
  let cursor = start;
  let protectedIndex = 0;
  while (cursor < content.length) {
    if (singleLine && (content[cursor] === "\n" || content[cursor] === "\r")) {
      return -1;
    }
    while (
      protectedIndex < protectedRanges.length
      && cursor >= protectedRanges[protectedIndex].end
    ) {
      protectedIndex += 1;
    }
    const protectedRange = protectedRanges[protectedIndex];
    if (protectedRange && cursor >= protectedRange.start) {
      cursor = protectedRange.end;
      continue;
    }
    const index = content.indexOf(delimiter, cursor);
    if (index < 0) return -1;
    if (singleLine && /[\r\n]/.test(content.slice(cursor, index))) return -1;
    if (isInsideTextRange(index, protectedRanges) || isEscaped(content, index)) {
      cursor = index + delimiter.length;
      continue;
    }
    if (
      delimiter === "$"
      && (content[index - 1] === "$" || content[index + 1] === "$")
    ) {
      cursor = index + 1;
      continue;
    }
    return index;
  }
  return -1;
}

function isInlineDollarMathCandidate(
  content: string,
  openerStart: number,
  bodyStart: number,
  bodyEnd: number,
  tokenEnd: number,
) {
  const body = content.slice(bodyStart, bodyEnd);
  if (!body || body !== body.trim() || /[\r\n]/.test(body)) return false;
  if (body[0].match(/\d/)) {
    if (tokenEnd < content.length && /\d/.test(content[tokenEnd])) return false;
    if (/[\u3400-\u9fff，。；！？]/.test(body)) return false;
    if (/\s+[A-Za-z]{2,}/.test(body)) return false;
  }
  return openerStart === 0 || content[openerStart - 1] !== "$";
}

function findStandaloneEnvironmentRanges(
  content: string,
  protectedRanges: TextRange[],
  existingRanges: MarkdownMathRange[],
) {
  const ranges: MarkdownMathRange[] = [];
  let cursor = 0;
  while (cursor < content.length) {
    const firstLineEnd = findLineEnd(content, cursor);
    if (!content.slice(cursor, firstLineEnd).replace(/\r$/, "").trim()) {
      cursor = Math.min(content.length, firstLineEnd + 1);
      continue;
    }
    const start = cursor;
    let end = firstLineEnd;
    cursor = Math.min(content.length, firstLineEnd + 1);
    while (cursor < content.length) {
      const lineEnd = findLineEnd(content, cursor);
      const line = content.slice(cursor, lineEnd).replace(/\r$/, "");
      if (!line.trim()) break;
      end = lineEnd;
      cursor = Math.min(content.length, lineEnd + 1);
    }
    const raw = content.slice(start, end);
    if (
      overlapsTextRange(start, end, protectedRanges)
      || overlapsMathRange(start, end, existingRanges)
      || /^\s*(?:[-+*]\s+|\d+[.)]\s+|>|#{1,6}\s+)/.test(raw)
    ) {
      continue;
    }
    const begin = /\\begin\{([A-Za-z*]+)\}/.exec(raw);
    if (!begin || !DISPLAY_ENVIRONMENTS.has(begin[1])) continue;
    const environmentEnd = `\\end{${begin[1]}}`;
    const closeIndex = raw.lastIndexOf(environmentEnd);
    const prefix = raw.slice(0, begin.index).trim();
    if (prefix && !startsLikeMathExpression(prefix)) continue;
    if (closeIndex < begin.index) {
      ranges.push({
        bodyEnd: content.length,
        bodyStart: start,
        closed: false,
        delimiter: "environment",
        displayMode: true,
        end: content.length,
        start,
      });
      break;
    }
    const suffix = raw.slice(closeIndex + environmentEnd.length).trim();
    if (suffix) continue;
    ranges.push({
      bodyEnd: end,
      bodyStart: start,
      closed: true,
      delimiter: "environment",
      displayMode: true,
      end,
      start,
    });
  }
  return ranges;
}

function findLineEnd(content: string, start: number) {
  const newline = content.indexOf("\n", start);
  return newline < 0 ? content.length : newline;
}

function startsLikeMathExpression(value: string) {
  if (/[*#>`]/.test(value)) return false;
  return /^[A-Za-z0-9_{}()[\]^+\-=\\.,\s]+$/.test(value);
}

function collectProtectedMarkdownRanges(content: string) {
  const fenceRanges = collectFenceRanges(content);
  const htmlRanges = collectHtmlProtectedRanges(content);
  const protectedRanges = mergeTextRanges([...fenceRanges, ...htmlRanges]);
  const inlineCodeRanges = collectInlineCodeRanges(content, protectedRanges);
  return mergeTextRanges([...protectedRanges, ...inlineCodeRanges]);
}

function collectFenceRanges(content: string) {
  const ranges: TextRange[] = [];
  const linePattern = /.*(?:\r?\n|$)/g;
  let active: { marker: string; size: number; start: number } | null = null;
  let match: RegExpExecArray | null;
  while ((match = linePattern.exec(content)) !== null) {
    const line = match[0];
    if (!line) break;
    const lineText = line.replace(/\r?\n$/, "");
    const fence = /^\s*(`{3,}|~{3,})(.*)$/.exec(lineText);
    if (!active && fence) {
      active = { marker: fence[1][0], size: fence[1].length, start: match.index };
      continue;
    }
    if (
      active
      && new RegExp(`^\\s*${active.marker}{${active.size},}\\s*$`).test(lineText)
    ) {
      ranges.push({ start: active.start, end: match.index + line.length });
      active = null;
    }
  }
  if (active) ranges.push({ start: active.start, end: content.length });
  return ranges;
}

function collectHtmlProtectedRanges(content: string) {
  const ranges: TextRange[] = [];
  const blockPattern = /<(pre|code|script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi;
  let match: RegExpExecArray | null;
  while ((match = blockPattern.exec(content)) !== null) {
    ranges.push({ start: match.index, end: match.index + match[0].length });
  }
  const tagPattern = /<\/?([A-Za-z][A-Za-z0-9-]*)\b[^<>]*>/g;
  while ((match = tagPattern.exec(content)) !== null) {
    if (!HTML_TAG_NAMES.has(match[1].toLowerCase())) continue;
    ranges.push({ start: match.index, end: match.index + match[0].length });
  }
  const specialPattern = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<![A-Za-z][^<>]*>|<\?[\s\S]*?\?>/g;
  while ((match = specialPattern.exec(content)) !== null) {
    ranges.push({ start: match.index, end: match.index + match[0].length });
  }
  return ranges;
}

function collectInlineCodeRanges(content: string, protectedRanges: TextRange[]) {
  const ranges: TextRange[] = [];
  let cursor = 0;
  let protectedIndex = 0;
  while (cursor < content.length) {
    while (
      protectedIndex < protectedRanges.length
      && cursor >= protectedRanges[protectedIndex].end
    ) {
      protectedIndex += 1;
    }
    const protectedRange = protectedRanges[protectedIndex];
    if (protectedRange && cursor >= protectedRange.start) {
      cursor = protectedRange.end;
      continue;
    }
    if (content[cursor] !== "`") {
      cursor += 1;
      continue;
    }
    let size = 1;
    while (content[cursor + size] === "`") size += 1;
    const close = findMatchingBacktickRun(content, cursor + size, size);
    if (close >= 0) {
      ranges.push({ start: cursor, end: close + size });
      cursor = close + size;
      continue;
    }
    cursor += size;
  }
  return ranges;
}

function findMatchingBacktickRun(content: string, start: number, size: number) {
  let cursor = start;
  while (cursor < content.length) {
    const runStart = content.indexOf("`", cursor);
    if (runStart < 0) return -1;
    let runSize = 1;
    while (content[runStart + runSize] === "`") runSize += 1;
    if (runSize === size) return runStart;
    cursor = runStart + runSize;
  }
  return -1;
}

function mergeTextRanges(ranges: TextRange[]) {
  const sorted = ranges
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start);
  const merged: TextRange[] = [];
  for (const range of sorted) {
    const previous = merged[merged.length - 1];
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

function isInsideTextRange(index: number, ranges: TextRange[]) {
  return ranges.some((range) => index >= range.start && index < range.end);
}

function overlapsTextRange(start: number, end: number, ranges: TextRange[]) {
  return ranges.some((range) => start < range.end && end > range.start);
}

function overlapsMathRange(start: number, end: number, ranges: MarkdownMathRange[]) {
  return ranges.some((range) => start < range.end && end > range.start);
}

function isEscaped(content: string, index: number) {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && content[cursor] === "\\"; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}
