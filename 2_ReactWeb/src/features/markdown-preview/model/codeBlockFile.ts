const LANGUAGE_EXTENSION_MAP: Record<string, string> = {
  bash: "sh",
  c: "c",
  cpp: "cpp",
  csharp: "cs",
  css: "css",
  go: "go",
  html: "html",
  java: "java",
  javascript: "js",
  js: "js",
  json: "json",
  jsx: "jsx",
  markdown: "md",
  md: "md",
  mermaid: "mmd",
  php: "php",
  plaintext: "txt",
  python: "py",
  py: "py",
  rust: "rs",
  sh: "sh",
  sql: "sql",
  svg: "svg",
  ts: "ts",
  tsx: "tsx",
  typescript: "ts",
  xml: "xml",
  yaml: "yaml",
  yml: "yml",
};

export type CodeBlockSavePayload = {
  code: string;
  language: string;
};

export function buildCodeBlockRootFilePath(language: string) {
  const extension = resolveCodeBlockExtension(language);
  const timestamp = new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d+Z$/, "");
  const suffix = Math.random().toString(36).slice(2, 7);
  return `ai-code-${timestamp}-${suffix}.${extension}`;
}

function resolveCodeBlockExtension(language: string) {
  const normalized = language.trim().toLowerCase();
  if (!normalized) return "txt";
  return LANGUAGE_EXTENSION_MAP[normalized] ?? (normalized.replace(/[^a-z0-9]+/g, "") || "txt");
}
