import type { Pluggable } from "unified";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

const DISPLAY_MATH_DELIMITER = "$$";
const BRACKET_OPEN_DELIMITER = "\\[";
const BRACKET_CLOSE_DELIMITER = "\\]";

const DISPLAY_ENVIRONMENTS = [
  "align",
  "align\\*",
  "aligned",
  "alignedat",
  "alignat",
  "array",
  "bmatrix",
  "cases",
  "eqnarray",
  "eqnarray\\*",
  "gathered",
  "matrix",
  "pmatrix",
  "smallmatrix",
  "split",
  "vmatrix",
  "Vmatrix",
] as const;

const DISPLAY_ENVIRONMENT_PATTERN = new RegExp(
  `\\\\begin\\{(${DISPLAY_ENVIRONMENTS.join("|")})\\}`,
);

export const markdownMathRemarkPlugins: Pluggable[] = [remarkMath];
export const markdownMathRehypePlugins: Pluggable[] = [
  [rehypeKatex, { errorColor: "#d88f86" }],
];

export function normalizeMarkdownMath(content: string) {
  return protectTableMathPipes(
    normalizeLatexMathSyntax(
      wrapStandaloneMathEnvironments(
        normalizeInlineMathDelimiters(
          normalizeEscapedTableMathDelimiters(
            normalizeDisplayMathDelimiters(content),
          ),
        ),
      ),
    ),
  );
}

export function normalizeLatexForKatex(latex: string) {
  return latex
    .split("\n")
    .map(normalizeLatexLine)
    .join("\n")
    .trim();
}

function normalizeDisplayMathDelimiters(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let isInFence = false;
  let isInDisplayMath = false;

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      isInFence = !isInFence;
      output.push(line);
      continue;
    }

    if (isInFence) {
      output.push(line);
      continue;
    }

    const indent = line.match(/^\s*/)?.[0] ?? "";
    const contentPart = line.slice(indent.length);
    const contentTrimmed = contentPart.trim();

    if (contentTrimmed === DISPLAY_MATH_DELIMITER) {
      output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
      isInDisplayMath = true;
      continue;
    }

    if (contentTrimmed === BRACKET_OPEN_DELIMITER) {
      if (!hasFutureBracketMathClose(lines, lineIndex + 1)) {
        output.push(line);
        continue;
      }
      output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
      isInDisplayMath = true;
      continue;
    }

    if (contentTrimmed === BRACKET_CLOSE_DELIMITER) {
      output.push(isInDisplayMath ? `${indent}${DISPLAY_MATH_DELIMITER}` : line);
      if (isInDisplayMath) isInDisplayMath = false;
      continue;
    }

    if (!isInDisplayMath && contentTrimmed.startsWith(DISPLAY_MATH_DELIMITER)) {
      pushOpeningDisplayMathLine(output, indent, contentTrimmed.slice(DISPLAY_MATH_DELIMITER.length));
      isInDisplayMath = !contentTrimmed.endsWith(DISPLAY_MATH_DELIMITER) || contentTrimmed === DISPLAY_MATH_DELIMITER;
      if (contentTrimmed.endsWith(DISPLAY_MATH_DELIMITER) && contentTrimmed.length > DISPLAY_MATH_DELIMITER.length * 2) {
        isInDisplayMath = false;
      }
      continue;
    }

    if (!isInDisplayMath && contentTrimmed.startsWith(BRACKET_OPEN_DELIMITER)) {
      const closesOnCurrentLine = contentTrimmed.endsWith(BRACKET_CLOSE_DELIMITER);
      if (!closesOnCurrentLine && !hasFutureBracketMathClose(lines, lineIndex + 1)) {
        output.push(line);
        continue;
      }
      pushOpeningBracketMathLine(output, indent, contentTrimmed.slice(BRACKET_OPEN_DELIMITER.length));
      isInDisplayMath = !closesOnCurrentLine;
      continue;
    }

    if (isInDisplayMath && contentTrimmed.endsWith(DISPLAY_MATH_DELIMITER)) {
      pushClosingDisplayMathLine(output, indent, line, DISPLAY_MATH_DELIMITER);
      isInDisplayMath = false;
      continue;
    }

    if (isInDisplayMath && contentTrimmed.endsWith(BRACKET_CLOSE_DELIMITER)) {
      pushClosingDisplayMathLine(output, indent, line, BRACKET_CLOSE_DELIMITER);
      isInDisplayMath = false;
      continue;
    }

    output.push(line);
  }

  return output.join("\n");
}

function hasFutureBracketMathClose(lines: string[], startIndex: number) {
  for (let lineIndex = startIndex; lineIndex < lines.length; lineIndex += 1) {
    const trimmed = lines[lineIndex].trim();
    if (isFenceLine(trimmed)) return false;
    if (trimmed.endsWith(BRACKET_CLOSE_DELIMITER)) return true;
  }
  return false;
}

function normalizeInlineMathDelimiters(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let isInFence = false;
  let isInDisplayMath = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      isInFence = !isInFence;
      output.push(line);
      continue;
    }

    if (!isInFence && trimmed === DISPLAY_MATH_DELIMITER) {
      isInDisplayMath = !isInDisplayMath;
      output.push(line);
      continue;
    }

    if (isInFence || isInDisplayMath) {
      output.push(line);
      continue;
    }

    output.push(
      normalizeInlineDoubleDollarMath(
        line.replace(/\\\((.+?)\\\)/g, (_match, formula: string) => {
          const trimmedFormula = formula.trim();
          if (!trimmedFormula || trimmedFormula.includes("$")) {
            return _match;
          }
          return `$${trimmedFormula}$`;
        }),
      ),
    );
  }

  return output.join("\n");
}

function normalizeEscapedTableMathDelimiters(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let isInFence = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      isInFence = !isInFence;
      output.push(line);
      continue;
    }

    if (!isInFence && isLikelyTableLine(line) && line.includes("\\$")) {
      output.push(
        line
          .replace(/\\\$\\\$/g, DISPLAY_MATH_DELIMITER)
          .replace(/\\\$/g, "$"),
      );
      continue;
    }

    output.push(line);
  }

  return output.join("\n");
}

function normalizeInlineDoubleDollarMath(line: string) {
  let output = "";
  let cursor = 0;

  while (cursor < line.length) {
    const start = line.indexOf(DISPLAY_MATH_DELIMITER, cursor);
    if (start < 0) {
      output += line.slice(cursor);
      break;
    }
    const end = line.indexOf(DISPLAY_MATH_DELIMITER, start + DISPLAY_MATH_DELIMITER.length);
    if (end < 0) {
      output += line.slice(cursor);
      break;
    }

    const body = line.slice(start + DISPLAY_MATH_DELIMITER.length, end).trim();
    output += line.slice(cursor, start);
    output += body ? `$${body}$` : line.slice(start, end + DISPLAY_MATH_DELIMITER.length);
    cursor = end + DISPLAY_MATH_DELIMITER.length;
  }

  return output;
}

function pushOpeningDisplayMathLine(output: string[], indent: string, rest: string) {
  const body = rest.trim();
  output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
  if (!body) return;

  if (body.endsWith(DISPLAY_MATH_DELIMITER)) {
    const formula = body.slice(0, -DISPLAY_MATH_DELIMITER.length).trim();
    if (formula) {
      output.push(`${indent}${formula}`);
    }
    output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
    return;
  }

  output.push(`${indent}${body}`);
}

function pushOpeningBracketMathLine(output: string[], indent: string, rest: string) {
  const body = rest.trim();
  output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
  if (!body) return;

  if (body.endsWith(BRACKET_CLOSE_DELIMITER)) {
    const formula = body.slice(0, -BRACKET_CLOSE_DELIMITER.length).trim();
    if (formula) {
      output.push(`${indent}${formula}`);
    }
    output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
    return;
  }

  output.push(`${indent}${body}`);
}

function pushClosingDisplayMathLine(
  output: string[],
  indent: string,
  line: string,
  delimiter: string,
) {
  const delimiterIndex = line.lastIndexOf(delimiter);
  const formula = line.slice(0, delimiterIndex).trimEnd();
  if (formula.trim()) {
    output.push(formula);
  }
  output.push(`${indent}${DISPLAY_MATH_DELIMITER}`);
}

function wrapStandaloneMathEnvironments(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let paragraph: string[] = [];
  let isInFence = false;
  let isInDisplayMath = false;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    if (shouldWrapMathEnvironment(paragraph)) {
      output.push(DISPLAY_MATH_DELIMITER, ...paragraph, DISPLAY_MATH_DELIMITER);
    } else {
      output.push(...paragraph);
    }
    paragraph = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      flushParagraph();
      isInFence = !isInFence;
      output.push(line);
      continue;
    }

    if (!isInFence && trimmed === DISPLAY_MATH_DELIMITER) {
      flushParagraph();
      isInDisplayMath = !isInDisplayMath;
      output.push(line);
      continue;
    }

    if (isInFence || isInDisplayMath) {
      flushParagraph();
      output.push(line);
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      output.push(line);
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return output.join("\n");
}

function shouldWrapMathEnvironment(lines: string[]) {
  const text = lines.join("\n").trim();
  const match = DISPLAY_ENVIRONMENT_PATTERN.exec(text);
  if (!match) return false;
  if (!startsLikeMathExpression(text, match.index)) return false;
  return text.includes(`\\end{${match[1]}}`);
}

function startsLikeMathExpression(text: string, environmentIndex: number) {
  const prefix = text.slice(0, environmentIndex).trim();
  if (!prefix) return true;
  if (/[*#>`]/.test(prefix)) return false;
  return /^[A-Za-z0-9_{}()[\]^+\-=\\.,\s]+$/.test(prefix);
}

function normalizeLatexMathSyntax(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let isInFence = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      isInFence = !isInFence;
      output.push(line);
      continue;
    }
    output.push(isInFence ? line : normalizeLatexLine(line));
  }

  return output.join("\n");
}

function normalizeLatexLine(line: string) {
  return line
    .replace(/\\tag\{[^}]*\}/g, "")
    .replace(/\\label\{[^}]*\}/g, "")
    .replace(/\\nonumber\b/g, "")
    .replace(/\\displaystyle\b/g, "")
    .replace(/\\begin\{eqnarray\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{eqnarray\*?\}/g, "\\end{aligned}")
    .replace(/\\begin\{align\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{align\*?\}/g, "\\end{aligned}")
    .replace(/\\begin\{alignat\}\{\d+\}/g, "\\begin{aligned}")
    .replace(/\\end\{alignat\}/g, "\\end{aligned}")
    .replace(/\\begin\{tabular\}/g, "\\begin{array}")
    .replace(/\\end\{tabular\}/g, "\\end{array}");
}

function protectTableMathPipes(content: string) {
  const lines = content.split("\n");
  const output: string[] = [];
  let isInFence = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (isFenceLine(trimmed)) {
      isInFence = !isInFence;
      output.push(line);
      continue;
    }
    output.push(
      !isInFence && isLikelyTableLine(line) ? escapePipesInsideMath(line) : line,
    );
  }

  return output.join("\n");
}

function isLikelyTableLine(line: string) {
  return line.includes("|");
}

function escapePipesInsideMath(line: string) {
  let output = "";
  let cursor = 0;
  let mathDelimiter = "";
  let isInInlineCode = false;

  while (cursor < line.length) {
    const char = line[cursor];
    const nextTwo = line.slice(cursor, cursor + 2);

    if (!mathDelimiter && char === "`") {
      isInInlineCode = !isInInlineCode;
      output += char;
      cursor += 1;
      continue;
    }

    if (!isInInlineCode && !mathDelimiter && (nextTwo === "$$" || nextTwo === "\\[" || nextTwo === "\\(")) {
      mathDelimiter = nextTwo;
      output += nextTwo;
      cursor += 2;
      continue;
    }

    if (!isInInlineCode && !mathDelimiter && char === "$") {
      mathDelimiter = "$";
      output += char;
      cursor += 1;
      continue;
    }

    if (mathDelimiter && isMathDelimiterClose(line, cursor, mathDelimiter)) {
      const closeDelimiter = mathCloseDelimiter(mathDelimiter);
      mathDelimiter = "";
      output += closeDelimiter;
      cursor += closeDelimiter.length;
      continue;
    }

    if (mathDelimiter && char === "\\" && shouldUnescapeInMath(line[cursor + 1])) {
      output += line[cursor + 1];
      cursor += 2;
      continue;
    }

    if (mathDelimiter && char === "\\" && line[cursor + 1] === "|") {
      output += "\\|";
      cursor += 2;
      continue;
    }

    output += mathDelimiter && char === "|" ? "\\vert " : char;
    cursor += 1;
  }

  return output;
}

function shouldUnescapeInMath(char: string | undefined) {
  return char === "_" || char === "[" || char === "]";
}

function isMathDelimiterClose(line: string, cursor: number, delimiter: string) {
  return line.startsWith(mathCloseDelimiter(delimiter), cursor);
}

function mathCloseDelimiter(delimiter: string) {
  if (delimiter === "\\[") return "\\]";
  if (delimiter === "\\(") return "\\)";
  return delimiter;
}

function isFenceLine(trimmedLine: string) {
  return /^(```|~~~)/.test(trimmedLine);
}
