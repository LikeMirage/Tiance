import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import {
  createWorkspaceAssetUrl,
  normalizeWorkspaceAssetPath,
} from "./documentAssetUrls";

export type MarkdownAssetUrlResolver = (src: string | undefined) => string | undefined;

export function createMarkdownAssetUrlResolver(
  tab: DocumentTab | null,
): MarkdownAssetUrlResolver | undefined {
  if (!tab?.fileSource || !tab.filePath) {
    return undefined;
  }

  const source = tab.fileSource;
  const currentPath = normalizeWorkspaceAssetPath(tab.filePath);
  if (!currentPath) {
    return undefined;
  }

  if (source.kind === "project" || source.kind === "tool-folder") {
    return (src) => {
      const assetPath = resolveMarkdownAssetPath(currentPath, src);
      return assetPath ? createWorkspaceAssetUrl(source, assetPath) ?? src : src;
    };
  }

  return undefined;
}

function resolveMarkdownAssetPath(currentFilePath: string, src: string | undefined) {
  if (!src) {
    return null;
  }

  const cleanSrc = stripUrlSuffix(src.trim());
  if (!cleanSrc || isExternalAssetSrc(cleanSrc)) {
    return null;
  }

  const baseParts = cleanSrc.startsWith("/")
    ? []
    : currentFilePath.split("/").slice(0, -1);
  const srcParts = cleanSrc.replace(/\\/g, "/").replace(/^\/+/, "").split("/");
  const parts = [...baseParts];

  for (const part of srcParts) {
    if (!part || part === ".") {
      continue;
    }
    if (part === "..") {
      if (parts.length === 0) {
        return null;
      }
      parts.pop();
      continue;
    }
    parts.push(part);
  }

  return parts.length > 0 ? parts.join("/") : null;
}

function stripUrlSuffix(value: string) {
  const suffixIndex = value.search(/[?#]/);
  return suffixIndex >= 0 ? value.slice(0, suffixIndex) : value;
}

function isExternalAssetSrc(src: string) {
  return /^([a-z][a-z0-9+.-]*:|#)/i.test(src);
}
