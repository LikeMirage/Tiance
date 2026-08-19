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

function transformChildren(node: MdastNode, parentType: string | null) {
  if (!node.children || parentType === "link" || parentType === "code" || parentType === "inlineCode") {
    return;
  }
  const nextChildren: MdastNode[] = [];
  for (const child of node.children) {
    if (child.type === "inlineCode" && child.value && looksLikeInlineLocalPath(child.value)) {
      nextChildren.push({
        type: "link",
        url: encodeLocalPathLink(child.value.trim()),
        children: [{ type: "text", value: child.value }],
      });
      continue;
    }
    if (child.type !== "text" || !child.value) {
      transformChildren(child, child.type ?? null);
      nextChildren.push(child);
      continue;
    }
    nextChildren.push(...splitTextNode(child.value));
  }
  node.children = nextChildren;
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
