import type { EditorExternalPathReferenceRequest } from "../../../entities/editor/model/editorReference";
import type { ProjectFileDragData } from "../../../entities/project/model/projectFileDragData";
import type { DesktopPathEntry } from "../../../shared/types/desktopShell";

export type ComposerPathReference =
  | { kind: "external"; reference: EditorExternalPathReferenceRequest }
  | { kind: "project"; reference: ProjectFileDragData };

export function resolveComposerPathReference(
  entry: DesktopPathEntry,
  projectId: string,
  projectRootPath: string,
): ComposerPathReference | null {
  const normalizedPath = normalizeAbsolutePath(entry.path);
  if (!normalizedPath) return null;
  const normalizedEntry = { ...entry, path: normalizedPath };
  const relativePath = projectRelativePath(normalizedPath, projectRootPath);
  if (relativePath !== null) {
    return {
      kind: "project",
      reference: {
        kind: entry.kind,
        name: entry.name,
        path: relativePath,
        projectId,
      },
    };
  }
  return {
    kind: "external",
    reference: normalizedEntry,
  };
}

export function filePathEntries(files: File[]): DesktopPathEntry[] {
  return files.flatMap((file) => {
    const path = nativeFilePath(file);
    return path ? [{ kind: "file" as const, name: file.name, path }] : [];
  });
}

export function nativeFilePath(file: File): string | null {
  const value = (file as File & { path?: unknown }).path;
  if (typeof value !== "string" || !isAbsolutePath(value)) return null;
  return value;
}

function projectRelativePath(path: string, projectRootPath: string): string | null {
  const normalizedPath = normalizeAbsolutePath(path);
  const normalizedRoot = normalizeAbsolutePath(projectRootPath);
  if (!normalizedPath || !normalizedRoot) return null;

  const useCaseInsensitiveComparison = isWindowsPath(normalizedPath) && isWindowsPath(normalizedRoot);
  const comparablePath = useCaseInsensitiveComparison
    ? normalizedPath.toLocaleLowerCase()
    : normalizedPath;
  const comparableRoot = useCaseInsensitiveComparison
    ? normalizedRoot.toLocaleLowerCase()
    : normalizedRoot;
  if (comparablePath === comparableRoot) return ".";
  if (!comparablePath.startsWith(`${comparableRoot}/`)) return null;
  return normalizedPath.slice(normalizedRoot.length + 1);
}

function normalizeAbsolutePath(path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return isAbsolutePath(normalized) ? normalized : "";
}

function isAbsolutePath(path: string) {
  return /^[a-zA-Z]:[\\/]/.test(path) || /^[/\\]{2}[^/\\]/.test(path) || path.startsWith("/");
}

function isWindowsPath(path: string) {
  return /^[a-zA-Z]:\//.test(path) || path.startsWith("//");
}
