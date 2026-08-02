import { env } from "../../shared/config/env";
import { getProjectFileContent } from "../project/getProjectFileContent";

const THEME_PACKAGE_MANIFEST = "manifest.json";

export async function getThemeProjectPreviewUrl(projectId: string): Promise<string | null> {
  const manifestFile = await getProjectFileContent(projectId, THEME_PACKAGE_MANIFEST);
  const previewPath = readPreviewPath(manifestFile.content);
  if (!previewPath) return null;

  const assetUrl = `${env.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/files/asset`;
  const query = new URLSearchParams({
    path: previewPath,
    v: String(manifestFile.mtime_ms),
  });
  return `${assetUrl}?${query.toString()}`;
}

function readPreviewPath(content: string): string | null {
  try {
    const payload: unknown = JSON.parse(content);
    if (!payload || typeof payload !== "object") return null;
    const preview = (payload as { preview?: unknown }).preview;
    if (typeof preview !== "string") return null;

    const normalized = preview.replaceAll("\\", "/").replace(/^\.\//, "").trim();
    const parts = normalized.split("/");
    if (
      !normalized
      || normalized.startsWith("/")
      || parts.some((part) => !part || part === "." || part === "..")
    ) {
      return null;
    }
    return normalized;
  } catch {
    return null;
  }
}
