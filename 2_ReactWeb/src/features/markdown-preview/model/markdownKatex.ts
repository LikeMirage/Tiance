import katex from "katex";
import "katex/contrib/mhchem";

import { markdownKatexOptions, normalizeLatexForKatex } from "./markdownMath";

export type MarkdownKatexRenderResult = {
  error: string | null;
  html: string;
  source: string;
};

export function renderMarkdownKatex(
  latex: string,
  displayMode: boolean,
): MarkdownKatexRenderResult {
  const source = normalizeLatexForKatex(latex);
  if (!source) return { error: null, html: "", source };

  try {
    return {
      error: null,
      html: katex.renderToString(source, {
        ...markdownKatexOptions,
        displayMode,
        throwOnError: true,
      }),
      source,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "公式无法完整渲染";
    try {
      return {
        error: message,
        html: katex.renderToString(source, {
          ...markdownKatexOptions,
          displayMode,
          strict: "ignore",
          throwOnError: false,
        }),
        source,
      };
    } catch {
      return {
        error: message,
        html: `<code>${escapeHtml(source)}</code>`,
        source,
      };
    }
  }
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;");
}
