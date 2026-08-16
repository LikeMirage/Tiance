import { memo, useLayoutEffect, useMemo, useRef } from "react";
import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import "katex/dist/katex.min.css";

import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type { CodeBlockSavePayload } from "../model/codeBlockFile";
import {
  buildStreamingMarkdownSegments,
  splitStreamingMarkdownTail,
  type MarkdownSegment,
} from "../model/markdownSegments";
import {
  findMarkdownMathRanges,
  markdownMathRehypePlugins,
  markdownMathRemarkPlugins,
  normalizeMarkdownMath,
} from "../model/markdownMath";
import { renderMarkdownKatex } from "../model/markdownKatex";
import { useProgressiveMarkdownSegments } from "../model/useProgressiveMarkdownSegments";
import { MarkdownCodeBlock } from "./MarkdownCodeBlock";
import "./markdown-preview.css";

export type MarkdownPreviewProps = {
  content: string;
  isStreaming?: boolean;
  mathErrorMode?: "diagnostic" | "neutral";
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  renderStrategy?: "complete" | "progressive";
  resolveAssetUrl?: (src: string | undefined) => string | undefined;
};

const MAX_RICH_MARKDOWN_CHARS = 180_000;
const markdownHtmlSanitizeSchema = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "center",
    "details",
    "summary",
    "label",
  ],
  attributes: {
    ...defaultSchema.attributes,
    "*": [
      ...(defaultSchema.attributes?.["*"] ?? []),
      "align",
      "className",
      "style",
      "title",
    ],
    a: [
      ...(defaultSchema.attributes?.a ?? []),
      "href",
      "title",
      "target",
      "rel",
    ],
    img: [
      ...(defaultSchema.attributes?.img ?? []),
      "src",
      "alt",
      "title",
      "width",
      "height",
    ],
    td: [...(defaultSchema.attributes?.td ?? []), "align", "colSpan", "rowSpan"],
    th: [...(defaultSchema.attributes?.th ?? []), "align", "colSpan", "rowSpan"],
  },
};

export const MarkdownPreview = memo(function MarkdownPreview({
  content,
  isStreaming = false,
  mathErrorMode = "diagnostic",
  onPreviewHtmlCode,
  onSaveCodeBlock,
  renderStrategy = "complete",
  resolveAssetUrl,
}: MarkdownPreviewProps) {
  const shouldUsePlainLargePreview =
    renderStrategy === "complete" && content.length > MAX_RICH_MARKDOWN_CHARS;

  if (shouldUsePlainLargePreview) {
    return (
      <div className="markdown-preview markdown-preview--plain-large">
        <div className="markdown-preview__large-note">
          内容过长，已切换为纯文本预览以保持界面流畅。
        </div>
        <pre className="markdown-preview__plain-large-content">{content}</pre>
      </div>
    );
  }

  if (isStreaming) {
    return (
      <StreamingMarkdownPreview
        content={content}
        mathErrorMode={mathErrorMode}
        onPreviewHtmlCode={onPreviewHtmlCode}
        onSaveCodeBlock={onSaveCodeBlock}
        resolveAssetUrl={resolveAssetUrl}
      />
    );
  }

  if (renderStrategy === "progressive") {
    return (
      <ProgressiveMarkdownPreview
        content={content}
        mathErrorMode={mathErrorMode}
        onPreviewHtmlCode={onPreviewHtmlCode}
        onSaveCodeBlock={onSaveCodeBlock}
        resolveAssetUrl={resolveAssetUrl}
      />
    );
  }

  return (
    <div className={markdownPreviewClassName(undefined, mathErrorMode)}>
      <MarkdownRichContent
        codeBlocksAreStreaming={false}
        content={content}
        onPreviewHtmlCode={onPreviewHtmlCode}
        onSaveCodeBlock={onSaveCodeBlock}
        resolveAssetUrl={resolveAssetUrl}
      />
    </div>
  );
});

type MarkdownRichContentProps = {
  codeBlocksAreStreaming: boolean;
  content: string;
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  resolveAssetUrl?: (src: string | undefined) => string | undefined;
  tableFragment?: "continuation" | "first";
};

const MarkdownRichContent = memo(function MarkdownRichContent({
  codeBlocksAreStreaming,
  content,
  onPreviewHtmlCode,
  onSaveCodeBlock,
  resolveAssetUrl,
  tableFragment,
}: MarkdownRichContentProps) {
  const renderContent = useMemo(
    () => normalizeMarkdownMath(closeUnfinishedFence(content)),
    [content],
  );
  const markdownComponents = useMemo(() => ({
    a: ({ href, children }: { href?: string; children?: ReactNode }) => (
      <a href={href} target="_blank" rel="noreferrer">{children}</a>
    ),
    img: ({
      alt,
      height,
      src,
      title,
      width,
    }: {
      alt?: string;
      height?: number | string;
      src?: string;
      title?: string;
      width?: number | string;
    }) => (
      <img
        alt={alt ?? ""}
        height={height}
        src={resolveAssetUrl?.(src) ?? src}
        title={title}
        width={width}
      />
    ),
    pre: ({ children }: { children?: ReactNode }) => (
      <MarkdownCodeBlock
        isStreaming={codeBlocksAreStreaming}
        onPreviewHtmlCode={onPreviewHtmlCode}
        onSaveCodeBlock={onSaveCodeBlock}
      >
        {children}
      </MarkdownCodeBlock>
    ),
    table: ({ children }: { children?: ReactNode }) => tableFragment ? (
      <>{children}</>
    ) : (
      <div className="markdown-preview__table-wrap">
        <table>{children}</table>
      </div>
    ),
    thead: ({ children }: { children?: ReactNode }) => (
      tableFragment === "continuation" ? null : <thead>{children}</thead>
    ),
    td: ({ children, ...props }: TdHTMLAttributes<HTMLTableCellElement>) => (
      <td {...props}>{renderTableCellMath(children)}</td>
    ),
    th: ({ children, ...props }: ThHTMLAttributes<HTMLTableCellElement>) => (
      <th {...props}>{renderTableCellMath(children)}</th>
    ),
  }), [
    codeBlocksAreStreaming,
    onPreviewHtmlCode,
    onSaveCodeBlock,
    resolveAssetUrl,
    tableFragment,
  ]);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, ...markdownMathRemarkPlugins]}
      rehypePlugins={[
        rehypeRaw,
        [rehypeSanitize, markdownHtmlSanitizeSchema],
        ...markdownMathRehypePlugins,
      ]}
      components={markdownComponents}
    >
      {renderContent}
    </ReactMarkdown>
  );
});

function StreamingMarkdownPreview({
  content,
  mathErrorMode,
  onPreviewHtmlCode,
  onSaveCodeBlock,
  resolveAssetUrl,
}: Omit<MarkdownPreviewProps, "isStreaming">) {
  const { chunks, tail } = useMemo(
    () => buildStreamingMarkdownSegments(content),
    [content],
  );
  const { pendingDisplayMathBody, richContent } = useMemo(
    () => splitStreamingMarkdownTail(tail),
    [tail],
  );

  return (
    <div className={markdownPreviewClassName("markdown-preview--streaming", mathErrorMode)}>
      {chunks.map((chunk) => (
        <MarkdownRichContent
          key={chunk.id}
          codeBlocksAreStreaming
          content={chunk.content}
          onPreviewHtmlCode={onPreviewHtmlCode}
          onSaveCodeBlock={onSaveCodeBlock}
          resolveAssetUrl={resolveAssetUrl}
        />
      ))}
      {richContent ? (
        <MarkdownRichContent
          codeBlocksAreStreaming
          content={richContent}
          onPreviewHtmlCode={onPreviewHtmlCode}
          onSaveCodeBlock={onSaveCodeBlock}
          resolveAssetUrl={resolveAssetUrl}
        />
      ) : null}
      {pendingDisplayMathBody !== null ? (
        <StreamingPendingDisplayMath body={pendingDisplayMathBody} />
      ) : null}
    </div>
  );
}

function StreamingPendingDisplayMath({ body }: { body: string }) {
  const viewportRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollLeft = viewport.scrollWidth;
  }, [body]);

  return (
    <div
      className="markdown-preview__stream-pending-math"
      data-stream-pending-math="true"
      ref={viewportRef}
    >
      <span>{body || "\u00a0"}</span>
    </div>
  );
}

function ProgressiveMarkdownPreview({
  content,
  mathErrorMode,
  onPreviewHtmlCode,
  onSaveCodeBlock,
  resolveAssetUrl,
}: Omit<MarkdownPreviewProps, "isStreaming" | "renderStrategy">) {
  const { isComplete, visibleSegments } = useProgressiveMarkdownSegments(content);
  const renderItems = useMemo(
    () => groupProgressiveMarkdownSegments(visibleSegments),
    [visibleSegments],
  );

  return (
    <div
      aria-busy={!isComplete}
      className={markdownPreviewClassName("markdown-preview--progressive", mathErrorMode)}
    >
      {renderItems.map((item) => item.kind === "table" ? (
        <ProgressiveMarkdownTable
          key={item.id}
          onPreviewHtmlCode={onPreviewHtmlCode}
          onSaveCodeBlock={onSaveCodeBlock}
          resolveAssetUrl={resolveAssetUrl}
          segments={item.segments}
        />
      ) : (
        <MarkdownRichContent
          key={item.segment.id}
          codeBlocksAreStreaming={false}
          content={item.segment.content}
          onPreviewHtmlCode={onPreviewHtmlCode}
          onSaveCodeBlock={onSaveCodeBlock}
          resolveAssetUrl={resolveAssetUrl}
        />
      ))}
      {!isComplete ? (
        <LoadingStrip
          ariaLabel="正在分段渲染 Markdown 文档"
          label="正在渲染文档"
          mode="inline"
        />
      ) : null}
    </div>
  );
}

type ProgressiveMarkdownRenderItem =
  | { kind: "markdown"; segment: MarkdownSegment }
  | { id: string; kind: "table"; segments: MarkdownSegment[] };

const ProgressiveMarkdownTable = memo(function ProgressiveMarkdownTable({
  onPreviewHtmlCode,
  onSaveCodeBlock,
  resolveAssetUrl,
  segments,
}: {
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  resolveAssetUrl?: (src: string | undefined) => string | undefined;
  segments: MarkdownSegment[];
}) {
  return (
    <div className="markdown-preview__table-wrap">
      <table>
        {segments.map((segment) => (
          <MarkdownRichContent
            key={segment.id}
            codeBlocksAreStreaming={false}
            content={segment.content}
            onPreviewHtmlCode={onPreviewHtmlCode}
            onSaveCodeBlock={onSaveCodeBlock}
            resolveAssetUrl={resolveAssetUrl}
            tableFragment={segment.tablePartIndex === 0 ? "first" : "continuation"}
          />
        ))}
      </table>
    </div>
  );
});

function groupProgressiveMarkdownSegments(
  segments: MarkdownSegment[],
): ProgressiveMarkdownRenderItem[] {
  const items: ProgressiveMarkdownRenderItem[] = [];

  segments.forEach((segment) => {
    if (!segment.tableGroupId) {
      items.push({ kind: "markdown", segment });
      return;
    }

    const previous = items[items.length - 1];
    if (previous?.kind === "table" && previous.id === segment.tableGroupId) {
      previous.segments.push(segment);
      return;
    }
    items.push({ id: segment.tableGroupId, kind: "table", segments: [segment] });
  });

  return items;
}

function closeUnfinishedFence(content: string) {
  const fenceMatches = content.match(/```/g);
  if (!fenceMatches || fenceMatches.length % 2 === 0) return content;
  return `${content}\n\`\`\``;
}

function renderTableCellMath(children: ReactNode) {
  if (typeof children === "string") {
    return renderMathText(children, "cell-text");
  }

  if (Array.isArray(children)) {
    return children.flatMap((child, index) => {
      if (typeof child !== "string") return child;
      return renderMathText(child, `cell-text-${index}`);
    });
  }

  return children;
}

function renderMathText(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  const ranges = findMarkdownMathRanges(text).filter((range) => range.closed);
  ranges.forEach((range, segmentIndex) => {
    if (range.start > cursor) nodes.push(text.slice(cursor, range.start));
    const latex = text.slice(range.bodyStart, range.bodyEnd).trim();
    const mathNode = renderKatexMathNode(
      latex,
      shouldRenderTableMathAsDisplay(range.displayMode, latex),
      `${keyPrefix}-${segmentIndex}`,
    );
    nodes.push(mathNode ?? text.slice(range.start, range.end));
    cursor = range.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));

  return nodes;
}

function renderKatexMathNode(latex: string, displayMode: boolean, key: string) {
  if (!latex) return null;
  const rendered = renderMarkdownKatex(latex, displayMode);
  return (
    <span
      className={[
        "markdown-preview__table-cell-math",
        displayMode ? "markdown-preview__table-cell-math--display" : "",
        rendered.error ? "markdown-preview__math-error" : "",
      ].filter(Boolean).join(" ")}
      dangerouslySetInnerHTML={{ __html: rendered.html }}
      data-math-render-error={rendered.error ? "true" : undefined}
      key={key}
      title={rendered.error ?? undefined}
    />
  );
}

function shouldRenderTableMathAsDisplay(displayMode: boolean, latex: string) {
  if (displayMode) return true;
  return /\\begin\{(?:aligned|alignedat|align|align\*|eqnarray|eqnarray\*|cases|matrix|pmatrix|bmatrix)\}/.test(latex);
}

function markdownPreviewClassName(
  variant: string | undefined,
  mathErrorMode: MarkdownPreviewProps["mathErrorMode"],
) {
  return [
    "markdown-preview",
    variant,
    mathErrorMode === "neutral" ? "markdown-preview--neutral-math-errors" : "",
  ].filter(Boolean).join(" ");
}
