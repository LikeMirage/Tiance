export type LocalFileReference = {
  line: number | null;
  projectPath: string | null;
  rawPath: string;
  scope: "workspace" | "external";
} & (
  | { lookup: "path"; absolutePath: string }
  | { lookup: "name"; name: string; absolutePath: null }
);

export type LocalFileReferenceContext = {
  projectId: string | null;
  projectRootPath: string;
};

export type LocalFileNameIndex = ReadonlyMap<string, Extract<LocalFileReference, { lookup: "path" }>>;

export type LocalFileNameAvailability = {
  getSnapshot: () => LocalFileNameIndex | null;
  subscribe: (listener: () => void) => () => void;
};

const LOCAL_LINK_PREFIX = "tiance-local-path:";

export function encodeLocalPathLink(path: string) {
  return `${LOCAL_LINK_PREFIX}${encodeURIComponent(path)}`;
}

export function isEncodedLocalPathLink(href: string) {
  return href.startsWith(LOCAL_LINK_PREFIX);
}

/** Preserve explicit absolute Markdown destinations through URL sanitization. */
export function encodeAbsoluteLocalPathHref(href: string) {
  const decoded = decodeLocalPathHref(href);
  return decoded !== null && isWindowsAbsolutePath(decoded) ? encodeLocalPathLink(decoded) : null;
}

export function isLocalFileHref(href: string) {
  const decoded = decodeLocalPathHref(href);
  if (decoded === null) return false;
  const { path } = splitLineSuffix(decoded);
  return isWindowsAbsolutePath(path) || isProjectRelativePath(path);
}

export function resolveLocalFileReference(
  href: string,
  context: LocalFileReferenceContext,
): LocalFileReference | null {
  const decoded = decodeLocalPathHref(href);
  if (decoded === null) return null;
  const { line, path } = splitLineSuffix(decoded);
  const normalizedRoot = normalizeWindowsPath(context.projectRootPath);
  const absoluteInput = isWindowsAbsolutePath(path);

  if (!absoluteInput && (!context.projectId || !normalizedRoot || !isProjectRelativePath(path))) {
    return null;
  }

  // A bare filename is a lookup within the current project, including bare
  // Markdown destinations. ./a.md and paths with directories remain exact.
  if (!absoluteInput && !/[\\/]/.test(path)) {
    return { lookup: "name", name: path, absolutePath: null, line,
      projectPath: null, rawPath: decoded, scope: "workspace" };
  }

  const absolutePath = absoluteInput
    ? normalizeWindowsPath(path)
    : resolveRelativeWindowsPath(normalizedRoot, path);
  if (!absolutePath) return null;

  const projectPath = context.projectId && normalizedRoot
    ? toProjectRelativePath(absolutePath, normalizedRoot)
    : null;
  if (!absoluteInput && projectPath === null) return null;
  return {
    lookup: "path",
    absolutePath,
    line,
    projectPath,
    rawPath: decoded,
    scope: projectPath !== null ? "workspace" : "external",
  };
}

export function looksLikePlainAbsoluteLocalPath(value: string) {
  return /^(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+$/.test(value.trim());
}

function decodeLocalPathHref(href: string): string | null {
  const trimmed = href.trim();
  if (!trimmed) return null;
  if (isEncodedLocalPathLink(trimmed)) {
    try {
      return decodeURIComponent(trimmed.slice(LOCAL_LINK_PREFIX.length));
    } catch {
      return null;
    }
  }
  if (/^file:\/\//i.test(trimmed)) {
    try {
      const url = new URL(trimmed);
      const pathname = decodeURIComponent(url.pathname);
      if (url.host) return `\\\\${url.host}${pathname.replaceAll("/", "\\")}`;
      return pathname.replace(/^\/([A-Za-z]:)/, "$1").replaceAll("/", "\\");
    } catch {
      return null;
    }
  }
  if (/^[A-Za-z][A-Za-z\d+.-]*:/.test(trimmed) && !/^[A-Za-z]:[\\/]/.test(trimmed)) {
    return null;
  }
  try {
    return decodeURIComponent(trimmed);
  } catch {
    return trimmed;
  }
}

function splitLineSuffix(value: string) {
  const trimmed = value.trim().replace(/^<|>$/g, "");
  const match = trimmed.match(/^(.*?):(\d+)(?::\d+)?$/);
  if (!match || !isLikelyFilePath(match[1])) return { line: null, path: trimmed };
  return { line: Number(match[2]), path: match[1] };
}

function isLikelyFilePath(value: string) {
  return /[\\/]/.test(value) || /\.[A-Za-z\d_-]{1,12}$/.test(value);
}

function isWindowsAbsolutePath(value: string) {
  return /^(?:[A-Za-z]:[\\/]|\\\\)/.test(value.trim());
}

function isProjectRelativePath(value: string) {
  const trimmed = value.trim();
  return Boolean(
    trimmed
      && !trimmed.startsWith("#")
      && !trimmed.startsWith("/")
      && !trimmed.startsWith("\\")
      && (/[\\/]/.test(trimmed) || /\.[A-Za-z\d_-]{1,12}$/.test(trimmed)),
  );
}

function normalizeWindowsPath(value: string) {
  const trimmed = value.trim().replaceAll("/", "\\").replace(/\\+$/g, "");
  if (!trimmed) return "";
  const prefix = trimmed.startsWith("\\\\") ? "\\\\" : "";
  const body = prefix ? trimmed.slice(2) : trimmed;
  const parts = body.split(/\\+/);
  const resolved: string[] = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (resolved.length > 1) resolved.pop();
      continue;
    }
    resolved.push(part);
  }
  return `${prefix}${resolved.join("\\")}`;
}

function resolveRelativeWindowsPath(root: string, relativePath: string) {
  return normalizeWindowsPath(`${root}\\${relativePath}`);
}

function toProjectRelativePath(absolutePath: string, projectRoot: string) {
  const absoluteLower = absolutePath.toLocaleLowerCase();
  const rootLower = projectRoot.toLocaleLowerCase();
  if (absoluteLower === rootLower) return "";
  if (!absoluteLower.startsWith(`${rootLower}\\`)) return null;
  return absolutePath.slice(projectRoot.length + 1).replaceAll("\\", "/");
}
