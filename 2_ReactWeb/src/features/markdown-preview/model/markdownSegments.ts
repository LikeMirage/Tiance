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

function buildMarkdownSegments(
  content: string,
  boundaries: number[],
  contentEnd: number,
  maxChunkChars: number,
  idPrefix: string,
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
        id: `${idPrefix}-${chunkStart}`,
        content: content.slice(chunkStart, previousBoundary),
      });
      chunkStart = previousBoundary;
    }
    previousBoundary = boundary;
  });

  if (contentEnd > chunkStart) {
    chunks.push({
      id: `${idPrefix}-${chunkStart}`,
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

function findStableMarkdownBoundaries(content: string) {
  const boundaries: number[] = [];
  let inFence = false;
  let fenceMarker = "";
  const linePattern = /.*(?:\r?\n|$)/g;
  let match: RegExpExecArray | null;

  while ((match = linePattern.exec(content)) !== null) {
    const line = match[0];
    if (!line) break;

    const lineEnd = match.index + line.length;
    const lineText = line.replace(/\r?\n$/, "");
    const fenceMatch = /^\s*(```+|~~~+)/.exec(lineText);

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

    if (!inFence && lineText.trim() === "") {
      boundaries.push(lineEnd);
    }
  }

  return boundaries;
}
