import { normalizeMarkdownMath } from "../../markdown-preview/model/markdownMath";

const TOC_DIRECTIVE_LINE_PATTERN = /^(\s*)\[TOC\](\s*)$/gm;
const ESCAPED_TOC_DIRECTIVE_LINE_PATTERN = /^(\s*)\\\[TOC(?:\\\])?(\s*)$/gm;

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
