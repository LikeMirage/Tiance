import {
  escapeAmbiguousMarkdownDollars,
  findMarkdownMathRanges,
  normalizeLatexForKatex,
  normalizeMarkdownMath,
  type MarkdownMathRange,
} from "../../markdown-preview/model/markdownMath";

const TOC_DIRECTIVE_LINE_PATTERN = /^(\s*)\[TOC\](\s*)$/gm;
const ESCAPED_TOC_DIRECTIVE_LINE_PATTERN = /^(\s*)\\\[TOC(?:\\\])?(\s*)$/gm;

export type MarkdownVisualEditorSession = {
  editorContent: string;
  restore: (editorContent: string) => string;
};

export function prepareMarkdownForVisualEditor(content: string) {
  return normalizeMarkdownMath(content).replace(
    TOC_DIRECTIVE_LINE_PATTERN,
    "$1\\[TOC\\]$2",
  );
}

export function restoreMarkdownFromVisualEditor(content: string) {
  return content.replace(
    ESCAPED_TOC_DIRECTIVE_LINE_PATTERN,
    "$1[TOC]$2",
  );
}

export function createMarkdownVisualEditorSession(
  source: string,
): MarkdownVisualEditorSession {
  const editorContent = prepareMarkdownForVisualEditor(source);
  const dollarEscapeMappings = createDollarEscapeMappings(source, editorContent);
  const sourceFormulas = collectFormulaSnapshots(source);
  const preparedFormulas = collectFormulaSnapshots(editorContent, true);
  const canRestoreFormulaSources = sourceFormulas.length === preparedFormulas.length
    && sourceFormulas.every((formula, index) => (
      formula.displayMode === preparedFormulas[index]?.displayMode
    ));
  const mappings = canRestoreFormulaSources
    ? preparedFormulas.map((prepared, index) => ({
        fingerprint: prepared.fingerprint,
        source: sourceFormulas[index].raw,
      }))
    : [];

  return {
    editorContent,
    restore: (nextEditorContent) => restoreInsertedDollarEscapes(
      restoreFormulaSources(
        restoreMarkdownFromVisualEditor(nextEditorContent),
        mappings,
      ),
      dollarEscapeMappings,
    ),
  };
}

type FormulaSnapshot = {
  displayMode: boolean;
  fingerprint: string;
  raw: string;
};

function collectFormulaSnapshots(content: string, excludeTocEscape = false) {
  return findMarkdownMathRanges(content)
    .filter((range) => range.closed && !(
      excludeTocEscape && isEscapedTocRange(content, range)
    ))
    .map((range) => ({
      displayMode: range.displayMode,
      fingerprint: formulaFingerprint(content, range),
      raw: content.slice(range.start, range.end),
    }));
}

function restoreFormulaSources(
  content: string,
  mappings: Array<{ fingerprint: string; source: string }>,
) {
  if (mappings.length === 0) return content;
  const sourceQueues = new Map<string, string[]>();
  for (const mapping of mappings) {
    const queue = sourceQueues.get(mapping.fingerprint) ?? [];
    queue.push(mapping.source);
    sourceQueues.set(mapping.fingerprint, queue);
  }

  const ranges = findMarkdownMathRanges(content).filter((range) => range.closed);
  const currentCounts = new Map<string, number>();
  for (const range of ranges) {
    const fingerprint = formulaFingerprint(content, range);
    currentCounts.set(fingerprint, (currentCounts.get(fingerprint) ?? 0) + 1);
  }
  for (const [fingerprint, queue] of sourceQueues) {
    if (currentCounts.get(fingerprint) !== queue.length) {
      sourceQueues.delete(fingerprint);
    }
  }
  let output = "";
  let cursor = 0;
  for (const range of ranges) {
    const fingerprint = formulaFingerprint(content, range);
    const queue = sourceQueues.get(fingerprint);
    const originalSource = queue?.shift();
    if (!originalSource) continue;
    output += content.slice(cursor, range.start);
    output += originalSource;
    cursor = range.end;
  }
  output += content.slice(cursor);
  return output;
}

function formulaFingerprint(content: string, range: MarkdownMathRange) {
  const body = content.slice(range.bodyStart, range.bodyEnd);
  return `${range.displayMode ? "display" : "inline"}:${normalizeLatexForKatex(body)}`;
}

function isEscapedTocRange(content: string, range: MarkdownMathRange) {
  return range.delimiter === "\\["
    && /^\\\[TOC\\\]$/i.test(content.slice(range.start, range.end).trim());
}

type DollarEscapeMapping = {
  dollarOccurrenceIndex: number;
  line: string;
  lineOccurrenceIndex: number;
};

function createDollarEscapeMappings(source: string, editorContent: string) {
  const guardedSource = escapeAmbiguousMarkdownDollars(source);
  const insertedFlags = alignInsertedDollarEscapes(source, guardedSource);
  const editorOccurrences = findEscapedDollarIndexes(editorContent);
  if (insertedFlags.length !== editorOccurrences.length) return [];

  return insertedFlags.flatMap((inserted, occurrenceIndex) => {
    if (!inserted) return [];
    const dollarIndex = editorOccurrences[occurrenceIndex];
    if (dollarIndex === undefined) return [];
    return [locateEscapedDollar(editorContent, dollarIndex)];
  });
}

function alignInsertedDollarEscapes(source: string, guardedSource: string) {
  const flags: boolean[] = [];
  let sourceIndex = 0;
  let guardedIndex = 0;
  while (guardedIndex < guardedSource.length) {
    if (
      guardedSource[guardedIndex] === "\\"
      && guardedSource[guardedIndex + 1] === "$"
    ) {
      const wasAlreadyEscaped = source[sourceIndex] === "\\" && source[sourceIndex + 1] === "$";
      flags.push(!wasAlreadyEscaped);
      guardedIndex += 2;
      sourceIndex += wasAlreadyEscaped ? 2 : 1;
      continue;
    }
    guardedIndex += 1;
    sourceIndex += 1;
  }
  return flags;
}

function restoreInsertedDollarEscapes(
  content: string,
  mappings: DollarEscapeMapping[],
) {
  if (mappings.length === 0) return content;
  const lines = readLineRanges(content);
  const removable = mappings.flatMap((mapping) => {
    const matchingLine = lines
      .filter((line) => line.text === mapping.line)
      [mapping.lineOccurrenceIndex];
    if (!matchingLine) return [];
    const localDollarIndex = findEscapedDollarIndexes(matchingLine.text)
      [mapping.dollarOccurrenceIndex];
    return localDollarIndex === undefined
      ? []
      : [matchingLine.start + localDollarIndex - 1];
  }).sort((left, right) => right - left);

  let restored = content;
  for (const slashIndex of removable) {
    restored = restored.slice(0, slashIndex) + restored.slice(slashIndex + 1);
  }
  return restored;
}

function findEscapedDollarIndexes(content: string) {
  const indexes: number[] = [];
  for (let index = 1; index < content.length; index += 1) {
    if (content[index] !== "$" || content[index - 1] !== "\\") continue;
    let slashCount = 0;
    for (let cursor = index - 1; cursor >= 0 && content[cursor] === "\\"; cursor -= 1) {
      slashCount += 1;
    }
    if (slashCount % 2 === 1) indexes.push(index);
  }
  return indexes;
}

function readContainingLine(content: string, index: number) {
  const start = content.lastIndexOf("\n", index - 1) + 1;
  const nextLine = content.indexOf("\n", index);
  const end = nextLine < 0 ? content.length : nextLine;
  return content.slice(start, end);
}

function locateEscapedDollar(
  content: string,
  dollarIndex: number,
): DollarEscapeMapping {
  const lines = readLineRanges(content);
  const currentLineIndex = lines.findIndex((line) => (
    dollarIndex >= line.start && dollarIndex <= line.end
  ));
  const currentLine = lines[currentLineIndex];
  const line = currentLine?.text ?? readContainingLine(content, dollarIndex);
  const localDollarIndex = dollarIndex - (currentLine?.start ?? 0);
  return {
    dollarOccurrenceIndex: findEscapedDollarIndexes(line)
      .filter((index) => index < localDollarIndex).length,
    line,
    lineOccurrenceIndex: lines
      .slice(0, Math.max(0, currentLineIndex))
      .filter((candidate) => candidate.text === line).length,
  };
}

function readLineRanges(content: string) {
  const lines: Array<{ end: number; start: number; text: string }> = [];
  let start = 0;
  while (start <= content.length) {
    const newline = content.indexOf("\n", start);
    const end = newline < 0 ? content.length : newline;
    lines.push({ end, start, text: content.slice(start, end) });
    if (newline < 0) break;
    start = newline + 1;
  }
  return lines;
}
