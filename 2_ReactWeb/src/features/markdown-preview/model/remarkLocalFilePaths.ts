import { encodeLocalPathLink } from "../../../entities/local-file/model/localFileReference";

type MdastNode = {
  children?: MdastNode[];
  type?: string;
  url?: string;
  value?: string;
};

const WINDOWS_PATH_PATTERN = /(?:[A-Za-z]:[\\/]|\\\\)(?:[^\r\n<>"'`|?*]*?\.[A-Za-z\d_-]{1,12}(?::\d+)?|[^\s<>"'`|?*]+)/g;

export function remarkLocalFilePaths() {
  return (tree: MdastNode) => transformChildren(tree, null);
}

function transformChildren(node: MdastNode, parentType: string | null, directory: string | null = null) {
  if (!node.children || parentType === "link" || parentType === "code" || parentType === "inlineCode") {
    return;
  }
  const nextChildren: MdastNode[] = [];
  let precedingDirectory: string | null = null;
  for (const child of node.children) {
    // Read the original paragraph before its code/text becomes a link.
    const childDirectory = standaloneDirectory(child);
    if (child.type === "inlineCode" && child.value && looksLikeInlineLocalPath(child.value)) {
      const path = child.value.trim();
      nextChildren.push({
        type: "link",
        url: encodeLocalPathLink(directory && !/^(?:[A-Za-z]:[\\/]|\\\\)/.test(path)
          ? directory + path
          : path),
        children: [{ type: "text", value: child.value }],
      });
      continue;
    }
    if (child.type !== "text" || !child.value) {
      transformChildren(child, child.type ?? null,
        child.type === "list" ? precedingDirectory ?? directory : directory);
      nextChildren.push(child);
      precedingDirectory = childDirectory;
      continue;
    }
    nextChildren.push(...splitTextNode(child.value));
    precedingDirectory = null;
  }
  node.children = nextChildren;
}

/** Only an explicit absolute directory with a trailing separator supplies context. */
export function explicitLocalDirectory(value: string): string | null {
  const path = value.trim();
  return /^(?:[A-Za-z]:[\\/]|\\\\)[^\r\n<>"|?*]*$/.test(path) && /[\\/]$/.test(path) ? path : null;
}

function standaloneDirectory(node: MdastNode): string | null {
  if (node.type !== "paragraph" || node.children?.length !== 1) return null;
  const child = node.children[0];
  return (child.type === "inlineCode" || child.type === "text") && child.value
    ? explicitLocalDirectory(child.value)
    : null;
}

function looksLikeInlineLocalPath(value: string) {
  const trimmed = value.trim();
  return /^(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+$/.test(trimmed)
    || /^(?![A-Za-z][A-Za-z\d+.-]*:)[^\r\n]+[\\/][^\r\n]+$/.test(trimmed)
    || /^(?![A-Za-z][A-Za-z\d+.-]*:)[^\r\n\\/]+\.[A-Za-z\d_-]{1,12}(?::\d+)?$/.test(trimmed);
}

function splitTextNode(value: string): MdastNode[] {
  const result: MdastNode[] = [];
  let offset = 0;
  for (const match of value.matchAll(WINDOWS_PATH_PATTERN)) {
    const start = match.index ?? 0;
    const rawMatch = trimTrailingPunctuation(match[0]);
    if (!rawMatch) continue;
    if (start > offset) result.push({ type: "text", value: value.slice(offset, start) });
    result.push({
      type: "link",
      url: encodeLocalPathLink(rawMatch),
      children: [{ type: "text", value: rawMatch }],
    });
    offset = start + rawMatch.length;
  }
  if (offset < value.length) result.push({ type: "text", value: value.slice(offset) });
  return result.length > 0 ? result : [{ type: "text", value }];
}

function trimTrailingPunctuation(value: string) {
  return value.replace(/[.,;!?，。；！？)\]}]+$/g, "");
}
