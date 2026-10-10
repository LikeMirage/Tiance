import type { toJsxRuntime } from "hast-util-to-jsx-runtime";

type MarkdownNode = Parameters<typeof toJsxRuntime>[0];
export type MarkdownRenderRoot = Extract<MarkdownNode, { type: "root" }>;
export type MarkdownRenderElement = Extract<MarkdownRenderRoot["children"][number], { type: "element" }>;

export type MarkdownRenderDocument = {
  html: string;
  blocks: string[];
  slots: MarkdownRenderElement[];
  cacheWeight: number;
};

export const MARKDOWN_BLOCK_PREFIX = "tiance-markdown-block:";
