import {
  findMarkdownMathRanges,
  findPendingMarkdownMathRange,
  isOffsetInsideMathRange,
  type MarkdownMathRange,
} from "./markdownMathScanner";
import { explicitLocalDirectory } from "./remarkLocalFilePaths";

export type MarkdownSegment = {
  content: string;
  id: string;
  tableGroupId?: string;
  tablePartIndex?: number;
};

export type StreamingMarkdownSegments = {
  chunks: MarkdownSegment[];
  tail: string;
};

export type StreamingMarkdownTailParts = {
  pendingDisplayMathBody: string | null;
  richContent: string;
};

export const MAX_PROGRESSIVE_MARKDOWN_CHUNK_CHARS = 6_000;
export const MAX_STREAM_MARKDOWN_CHUNK_CHARS = 12_000;

export function buildProgressiveMarkdownSegments(
  content: string,
  maxChunkChars = MAX_PROGRESSIVE_MARKDOWN_CHUNK_CHARS,
): MarkdownSegment[] {
  if (!content) return [];

  const boundaries = findStableMarkdownBoundaries(content);
  if (boundaries[boundaries.length - 1] !== content.length) {
    boundaries.push(content.length);
  }
  return buildMarkdownSegments(
    content,
    boundaries,
    content.length,
    maxChunkChars,
    "progressive-md",
  ).flatMap((segment) => splitOversizedGfmTable(segment, maxChunkChars));
}

export function buildStreamingMarkdownSegments(
  content: string,
  maxChunkChars = MAX_STREAM_MARKDOWN_CHUNK_CHARS,
): StreamingMarkdownSegments {
  const boundaries = findStableMarkdownBoundaries(content);
  const stableLength = boundaries[boundaries.length - 1] ?? 0;

  return {
    chunks: buildMarkdownSegments(
      content,
      boundaries,
      stableLength,
      maxChunkChars,
      "stream-md",
    ),
    tail: content.slice(stableLength),
  };
}

/** One renderer's derived cache, never a copy of the message authority.
 * Keep the last packing chunk and all open syntax in the rescan region. Edits,
 * retry resets and shorter replacements invalidate the cache without truncation.
 */
export function createStreamingMarkdownSegmenter(maxChunkChars = MAX_STREAM_MARKDOWN_CHUNK_CHARS) {
  let previousContent = "";
  let frozen: MarkdownSegment[] = [];
  let scanStart = 0;
  let previousResult: StreamingMarkdownSegments = { chunks: [], tail: "" };
  return (content: string): StreamingMarkdownSegments => {
    if (content === previousContent) return previousResult;
    if (!content.startsWith(previousContent)) {
      frozen = [];
      scanStart = 0;
    }
    const suffix = content.slice(scanStart);
    let reusableEnd = suffix.length;
    const protectedRanges: { start: number; end: number }[] = [];
    const boundaries = findStableMarkdownBoundaries(suffix, (offset) => {
      reusableEnd = Math.min(reusableEnd, offset);
    }, (range) => protectedRanges.push(range));
    const stableLength = boundaries[boundaries.length - 1] ?? 0;
    const chunks = buildMarkdownSegments(
      suffix, boundaries, stableLength, maxChunkChars, "stream-md", scanStart,
    );
    previousResult = { chunks: [...frozen, ...chunks], tail: suffix.slice(stableLength) };
    let consumed = 0;
    let reusableCount = 0;
    let reusableLength = 0;
    for (let index = 0; index < chunks.length - 1; index += 1) {
      const end = consumed + chunks[index].content.length;
      if (end > reusableEnd) break;
      if (suffix[end - 1] === "\n" && !protectedRanges.some((range) => range.start < end && end < range.end)) {
        reusableCount = index + 1;
        reusableLength = end;
      }
      consumed = end;
    }
    for (let index = 0; index < reusableCount; index += 1) frozen.push(chunks[index]);
    scanStart += reusableLength;
    previousContent = content;
    return previousResult;
  };
}

/**
 * Keeps an unfinished standalone display formula out of the rich Markdown
 * parser. The source remains untouched in the conversation; only the growing
 * tail receives a single-line pending presentation until its closer arrives.
 */
export function splitStreamingMarkdownTail(
  content: string,
): StreamingMarkdownTailParts {
  const pendingRange = findPendingMarkdownMathRange(content);
  if (!pendingRange) {
    return { pendingDisplayMathBody: null, richContent: content };
  }

  if (
    !pendingRange.displayMode
    || !startsAtStandaloneLinePosition(content, pendingRange.start)
  ) {
    return {
      pendingDisplayMathBody: null,
      richContent: escapePendingMathOpener(content, pendingRange),
    };
  }

  return {
    pendingDisplayMathBody: content.slice(
      pendingRange.bodyStart,
      pendingRange.bodyEnd,
    ),
    richContent: content.slice(0, pendingRange.start),
  };
}

function escapePendingMathOpener(content: string, range: MarkdownMathRange) {
  const opener = content.slice(range.start, range.bodyStart);
  const escapedOpener = opener === "$$"
    ? "\\$\\$"
    : opener === "$"
      ? "\\$"
      : opener === "\\("
        ? "\\\\("
        : opener === "\\["
          ? "\\\\["
          : opener;
  return content.slice(0, range.start) + escapedOpener + content.slice(range.bodyStart);
}

function startsAtStandaloneLinePosition(content: string, start: number) {
  const lineStart = content.lastIndexOf("\n", start - 1) + 1;
  return content.slice(lineStart, start).trim() === "";
}

function buildMarkdownSegments(
  content: string,
  boundaries: number[],
  contentEnd: number,
  maxChunkChars: number,
  idPrefix: string,
  idOffset = 0,
) {
  const chunks: MarkdownSegment[] = [];
  let chunkStart = 0;
  let previousBoundary = 0;

  boundaries.forEach((boundary) => {
    if (
      boundary - chunkStart > maxChunkChars &&
      previousBoundary > chunkStart
    ) {
      chunks.push({
        id: `${idPrefix}-${idOffset + chunkStart}`,
        content: content.slice(chunkStart, previousBoundary),
      });
      chunkStart = previousBoundary;
    }
    previousBoundary = boundary;
  });

  if (contentEnd > chunkStart) {
    chunks.push({
      id: `${idPrefix}-${idOffset + chunkStart}`,
      content: content.slice(chunkStart, contentEnd),
    });
  }

  return chunks;
}

function splitOversizedGfmTable(
  segment: MarkdownSegment,
  maxChunkChars: number,
): MarkdownSegment[] {
  if (segment.content.length <= maxChunkChars) return [segment];

  const lines = segment.content.match(/.*(?:\r?\n|$)/g)?.filter(Boolean) ?? [];
  let tableStart = 0;
  while (tableStart < lines.length && lines[tableStart].trim() === "") {
    tableStart += 1;
  }

  const header = lines[tableStart];
  const delimiter = lines[tableStart + 1];
  if (!header || !delimiter || !isGfmTableHeader(header, delimiter)) {
    return [segment];
  }

  let tableEnd = lines.length;
  while (tableEnd > tableStart + 2 && lines[tableEnd - 1].trim() === "") {
    tableEnd -= 1;
  }
  const bodyRows = lines.slice(tableStart + 2, tableEnd);
  if (bodyRows.length === 0 || bodyRows.some((line) => !hasUnescapedPipe(line))) {
    return [segment];
  }

  const leadingWhitespace = lines.slice(0, tableStart).join("");
  const trailingWhitespace = lines.slice(tableEnd).join("");
  const tablePrefix = `${header}${delimiter}`;
  const tableChunks: MarkdownSegment[] = [];
  let currentRows: string[] = [];
  let currentRowsLength = 0;

  const flushRows = () => {
    if (currentRows.length === 0) return;
    const chunkIndex = tableChunks.length;
    tableChunks.push({
      id: `${segment.id}-table-${chunkIndex}`,
      content: `${chunkIndex === 0 ? leadingWhitespace : ""}${tablePrefix}${currentRows.join("")}`,
      tableGroupId: segment.id,
      tablePartIndex: chunkIndex,
    });
    currentRows = [];
    currentRowsLength = 0;
  };

  bodyRows.forEach((row) => {
    if (
      currentRows.length > 0 &&
      tablePrefix.length + currentRowsLength + row.length > maxChunkChars
    ) {
      flushRows();
    }
    currentRows.push(row);
    currentRowsLength += row.length;
  });
  flushRows();

  if (trailingWhitespace && tableChunks.length > 0) {
    const lastIndex = tableChunks.length - 1;
    tableChunks[lastIndex] = {
      ...tableChunks[lastIndex],
      content: `${tableChunks[lastIndex].content}${trailingWhitespace}`,
    };
  }
  return tableChunks;
}

function isGfmTableHeader(header: string, delimiter: string) {
  if (!hasUnescapedPipe(header)) return false;
  const normalizedDelimiter = delimiter.trim().replace(/^\||\|$/g, "");
  const cells = normalizedDelimiter.split("|").map((cell) => cell.trim());
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function hasUnescapedPipe(line: string) {
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] !== "|") continue;
    let slashCount = 0;
    let cursor = index - 1;
    while (cursor >= 0 && line[cursor] === "\\") {
      slashCount += 1;
      cursor -= 1;
    }
    if (slashCount % 2 === 0) return true;
  }
  return false;
}

function findStableMarkdownBoundaries(
  content: string,
  onUnstableStart?: (offset: number) => void,
  onProtectedRange?: (range: { start: number; end: number }) => void,
) {
  const boundaries: number[] = [];
  const mathRanges = findMarkdownMathRanges(content, onUnstableStart, onProtectedRange);
  let inFence = false;
  let fenceMarker = "";
  let inDirectoryList = false;
  let directoryStart = 0;
  const linePattern = /.*(?:\r?\n|$)/g;
  let match: RegExpExecArray | null;

  while ((match = linePattern.exec(content)) !== null) {
    const line = match[0];
    if (!line) break;

    const lineEnd = match.index + line.length;
    const lineText = line.replace(/\r?\n$/, "");
    const fenceMatch = /^\s*(```+|~~~+)/.exec(lineText);

    if (!inFence && lineText.trim()) {
      const directory = explicitLocalDirectory(lineText.trim().replace(/^`([^`]+)`$/, "$1"));
      // Keep an explicit directory and its following list in the same render
      // segment, including the growing streaming tail and loose-list blanks.
      if (directory && !inDirectoryList) {
        inDirectoryList = true;
        directoryStart = match.index;
      } else if (!directory && !/^(?:\s+|(?:[-+*]|\d+[.)])\s)/.test(lineText)) {
        if (inDirectoryList) onProtectedRange?.({ start: directoryStart, end: match.index });
        inDirectoryList = false;
      }
    }

    if (fenceMatch) {
      const marker = fenceMatch[1][0];
      if (!inFence) {
        inFence = true;
        fenceMarker = marker;
      } else if (marker === fenceMarker) {
        inFence = false;
        boundaries.push(lineEnd);
      }
    }

    if (
      !inFence
      && !inDirectoryList
      && lineText.trim() === ""
      && !isOffsetInsideMathRange(lineEnd, mathRanges)
    ) {
      boundaries.push(lineEnd);
    }
  }

  if (inDirectoryList) onUnstableStart?.(directoryStart);
  return boundaries;
}
