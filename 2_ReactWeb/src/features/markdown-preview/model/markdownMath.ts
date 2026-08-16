import type { Pluggable } from "unified";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

import {
  escapeAmbiguousMarkdownDollars,
  findMarkdownMathRanges,
  type MarkdownMathRange,
} from "./markdownMathScanner";

export {
  escapeAmbiguousMarkdownDollars,
  findMarkdownMathRanges,
  isOffsetInsideMathRange,
} from "./markdownMathScanner";
export type { MarkdownMathRange } from "./markdownMathScanner";

export const markdownKatexOptions = {
  errorColor: "#d88f86",
  maxExpand: 1_000,
  maxSize: 20,
  output: "htmlAndMathml" as const,
  strict: "warn" as const,
  trust: false,
};

export const markdownMathRemarkPlugins: Pluggable[] = [
  [remarkMath, { singleDollarTextMath: true }],
];
export const markdownMathRehypePlugins: Pluggable[] = [
  [rehypeKatex, markdownKatexOptions],
];

/**
 * Builds a render-only Markdown copy. It never removes LaTeX commands and must
 * never be persisted as the user's source without the visual-editor restore step.
 */
export function normalizeMarkdownMath(content: string) {
  const guardedContent = escapeAmbiguousMarkdownDollars(content);
  const ranges = findMarkdownMathRanges(guardedContent);
  const normalizedDelimiters = replaceMathRanges(guardedContent, ranges);
  return protectGfmTableMathPipes(normalizedDelimiters);
}

export function normalizeLatexForKatex(latex: string) {
  return latex
    .replace(/\r\n?/g, "\n")
    .replace(/\\begin\{eqnarray\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{eqnarray\*?\}/g, "\\end{aligned}")
    .replace(/\\begin\{align\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{align\*?\}/g, "\\end{aligned}")
    .replace(/\\begin\{alignat\*?\}\{(\d+)\}/g, "\\begin{alignedat}{$1}")
    .replace(/\\end\{alignat\*?\}/g, "\\end{alignedat}")
    .replace(/\\begin\{gather\*?\}/g, "\\begin{gathered}")
    .replace(/\\end\{gather\*?\}/g, "\\end{gathered}")
    .replace(/\\begin\{tabular\}/g, "\\begin{array}")
    .replace(/\\end\{tabular\}/g, "\\end{array}")
    .trim();
}

function replaceMathRanges(content: string, ranges: MarkdownMathRange[]) {
  let output = "";
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    output += content.slice(cursor, range.start);
    output += normalizeMathRange(content, range);
    cursor = range.end;
  }
  output += content.slice(cursor);
  return output;
}

function normalizeMathRange(content: string, range: MarkdownMathRange) {
  const raw = content.slice(range.start, range.end);
  if (!range.closed || range.delimiter === "$") return raw;
  const body = content.slice(range.bodyStart, range.bodyEnd);
  if (range.delimiter === "\\(") return `$${body}$`;

  if (!isWholeLineRange(content, range)) {
    return raw;
  }

  const indent = readLineIndent(content, range.start);
  const bodyLines = body
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trim() ? `${indent}${line.trimEnd()}` : "")
    .join("\n")
    .trim();
  return bodyLines
    ? `${indent}$$\n${bodyLines}\n${indent}$$`
    : raw;
}

function isWholeLineRange(content: string, range: MarkdownMathRange) {
  const lineStart = content.lastIndexOf("\n", range.start - 1) + 1;
  const nextLine = content.indexOf("\n", range.end);
  const lineEnd = nextLine < 0 ? content.length : nextLine;
  return content.slice(lineStart, lineEnd).trim() === content.slice(range.start, range.end).trim();
}

function readLineIndent(content: string, index: number) {
  const lineStart = content.lastIndexOf("\n", index - 1) + 1;
  return /^\s*/.exec(content.slice(lineStart, index))?.[0] ?? "";
}

function protectGfmTableMathPipes(content: string) {
  const lines = content.split("\n");
  const tableLines = findGfmTableLineIndexes(lines);
  return lines
    .map((line, index) => tableLines.has(index) ? escapeMathPipesInTableLine(line) : line)
    .join("\n");
}

function findGfmTableLineIndexes(lines: string[]) {
  const indexes = new Set<number>();
  for (let index = 0; index + 1 < lines.length; index += 1) {
    if (!isGfmTableHeader(lines[index], lines[index + 1])) continue;
    indexes.add(index);
    indexes.add(index + 1);
    let row = index + 2;
    while (row < lines.length && lines[row].trim() && hasUnescapedPipe(lines[row])) {
      indexes.add(row);
      row += 1;
    }
    index = row - 1;
  }
  return indexes;
}

function isGfmTableHeader(header: string, delimiter: string) {
  if (!hasUnescapedPipe(header)) return false;
  const cells = delimiter.trim().replace(/^\||\|$/g, "").split("|");
  return cells.length > 1 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
}

function hasUnescapedPipe(line: string) {
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] === "|" && !isEscaped(line, index)) return true;
  }
  return false;
}

function escapeMathPipesInTableLine(line: string) {
  const ranges = findMarkdownMathRanges(line).filter((range) => range.closed);
  if (ranges.length === 0) return line;
  let output = "";
  let cursor = 0;
  for (const range of ranges) {
    output += line.slice(cursor, range.bodyStart);
    output += escapeLatexPipes(line.slice(range.bodyStart, range.bodyEnd));
    output += line.slice(range.bodyEnd, range.end);
    cursor = range.end;
  }
  output += line.slice(cursor);
  return output;
}

function escapeLatexPipes(latex: string) {
  let output = "";
  for (let index = 0; index < latex.length; index += 1) {
    const char = latex[index];
    if (char === "|" && !isEscaped(latex, index)) {
      output += "\\vert ";
    } else {
      output += char;
    }
  }
  return output;
}

function isEscaped(content: string, index: number) {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && content[cursor] === "\\"; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}
