import type { DocumentLanguage } from "./editorDocument";

const extensionMap: Record<string, DocumentLanguage> = {
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "typescript",
  jsx: "javascript",
  py: "python",
  pyw: "python",
  html: "html",
  htm: "html",
  css: "css",
  scss: "css",
  less: "css",
  json: "json",
  jsonc: "json",
  jsonl: "json",
  md: "markdown",
  markdown: "markdown",
  xml: "html",
  svg: "html",
  yaml: "plaintext",
  yml: "plaintext",
  toml: "plaintext",
  ini: "plaintext",
  cfg: "plaintext",
  env: "plaintext",
  txt: "plaintext",
  log: "plaintext",
  sh: "plaintext",
  bash: "plaintext",
  zsh: "plaintext",
  ps1: "plaintext",
  bat: "plaintext",
  cmd: "plaintext",
  sql: "plaintext",
  graphql: "plaintext",
  gql: "plaintext",
};

const fileNameMap: Record<string, DocumentLanguage> = {
  dockerfile: "plaintext",
  makefile: "plaintext",
  license: "plaintext",
  ".gitignore": "plaintext",
  ".env": "plaintext",
};

export function resolveLanguageId(fileName: string): DocumentLanguage {
  const dotIndex = fileName.lastIndexOf(".");
  if (dotIndex >= 0) {
    const ext = fileName.slice(dotIndex + 1).toLowerCase();
    if (extensionMap[ext]) return extensionMap[ext];
  }
  const lower = fileName.toLowerCase();
  if (fileNameMap[lower]) return fileNameMap[lower];
  return "plaintext";
}

export function isTextFile(fileName: string): boolean {
  const dotIndex = fileName.lastIndexOf(".");
  if (dotIndex < 0) return false;
  const ext = fileName.slice(dotIndex + 1).toLowerCase();
  return ext in extensionMap || ext === "lock" || ext === "toml" || ext === "yml" || ext === "yaml";
}
