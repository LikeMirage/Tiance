import bash from "@shikijs/langs/bash";
import css from "@shikijs/langs/css";
import html from "@shikijs/langs/html";
import javascript from "@shikijs/langs/javascript";
import json from "@shikijs/langs/json";
import jsx from "@shikijs/langs/jsx";
import markdown from "@shikijs/langs/markdown";
import python from "@shikijs/langs/python";
import tsx from "@shikijs/langs/tsx";
import typescript from "@shikijs/langs/typescript";
import xml from "@shikijs/langs/xml";
import yaml from "@shikijs/langs/yaml";
import githubDark from "@shikijs/themes/github-dark";
import githubDarkDefault from "@shikijs/themes/github-dark-default";
import githubLight from "@shikijs/themes/github-light";
import githubLightDefault from "@shikijs/themes/github-light-default";
import type { HighlighterCore } from "shiki/core";
import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

const DARK_THEME = "github-dark-default";
const LIGHT_THEME = "github-light";
const SUPPORTED_THEMES = new Set([
  "github-dark",
  "github-dark-default",
  "github-light",
  "github-light-default",
]);

export type CodeHighlightThemeName =
  | "github-dark"
  | "github-dark-default"
  | "github-light"
  | "github-light-default";

const SUPPORTED_LANGUAGES = new Set([
  "bash",
  "css",
  "html",
  "javascript",
  "json",
  "jsx",
  "markdown",
  "python",
  "tsx",
  "typescript",
  "xml",
  "yaml",
]);

const LANGUAGE_ALIASES: Record<string, string> = {
  htm: "html",
  js: "javascript",
  md: "markdown",
  py: "python",
  shell: "bash",
  sh: "bash",
  svg: "xml",
  ts: "typescript",
  yml: "yaml",
};

let highlighterPromise: Promise<HighlighterCore> | null = null;

export async function highlightCodeToHtml(
  code: string,
  language: string,
  themeName: string,
) {
  const highlighter = await getHighlighter();
  return highlighter.codeToHtml(code, {
    lang: normalizeLanguage(language),
    theme: normalizeTheme(themeName),
  });
}

function getHighlighter() {
  highlighterPromise ??= createHighlighterCore({
    engine: createJavaScriptRegexEngine(),
    langs: [
      bash,
      css,
      html,
      javascript,
      json,
      jsx,
      markdown,
      python,
      tsx,
      typescript,
      xml,
      yaml,
    ],
    themes: [githubDark, githubDarkDefault, githubLight, githubLightDefault],
    warnings: false,
  });
  return highlighterPromise;
}

export function getFallbackCodeHighlightThemeName(themeMode: "dark" | "light"): CodeHighlightThemeName {
  return themeMode === "light" ? LIGHT_THEME : DARK_THEME;
}

function normalizeTheme(themeName: string): CodeHighlightThemeName {
  const normalized = themeName.trim().toLowerCase();
  return SUPPORTED_THEMES.has(normalized)
    ? normalized as CodeHighlightThemeName
    : DARK_THEME;
}

function normalizeLanguage(language: string) {
  const normalized = language.trim().toLowerCase();
  const aliased = LANGUAGE_ALIASES[normalized] ?? normalized;
  return SUPPORTED_LANGUAGES.has(aliased) ? aliased : "text";
}
