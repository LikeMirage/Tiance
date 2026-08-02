import { Children, isValidElement, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import katex from "katex";

import type { CodeBlockSavePayload } from "../model/codeBlockFile";
import { normalizeLatexForKatex } from "../model/markdownMath";
import {
  formatSaveStateLabel,
  runCodeBlockSaveQueue,
  runKeyboardAction,
  runPointerAction,
  type SaveState,
} from "./markdownCodeBlockActions";
import { MarkdownMermaidBlock } from "./MarkdownMermaidBlock";

const MAX_HIGHLIGHTED_CODE_CHARS = 20_000;
const MAX_HIGHLIGHT_CACHE_ENTRIES = 100;
const highlightedCodeCache = new Map<string, string>();

export function MarkdownCodeBlock({
  children,
  isStreaming,
  onPreviewHtmlCode,
  onSaveCodeBlock,
}: {
  children: ReactNode;
  isStreaming: boolean;
  onPreviewHtmlCode?: (html: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
}) {
  const [copied, setCopied] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [pendingSaveCount, setPendingSaveCount] = useState(0);
  const [isExpanded, setIsExpanded] = useState(false);
  const codePreRef = useRef<HTMLDivElement>(null);
  const saveQueueRef = useRef<CodeBlockSavePayload[]>([]);
  const isSaveQueueRunningRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const child = Children.toArray(children)[0];
  const codeElement = isValidElement(child) ? child as ReactElement<{
    children?: ReactNode;
    className?: string;
  }> : null;
  const language = getCodeLanguage(codeElement?.props.className);
  const code = reactNodeToText(codeElement?.props.children ?? children);
  const highlightThemeName = getCodeHighlightThemeName();
  const canPreviewHtml = Boolean(onPreviewHtmlCode && isHtmlLanguage(language));
  const canPreviewLatex = isLatexLanguage(language) && code.trim().length > 0;
  const canSave = Boolean(onSaveCodeBlock);
  const canExpand = shouldOfferCodeExpand(code);
  const highlightedHtml = useHighlightedCode(
    code,
    language,
    highlightThemeName,
    !isStreaming && shouldHighlightCode(language) && code.length <= MAX_HIGHLIGHTED_CODE_CHARS,
  );
  const renderedHighlightedHtml = isStreaming ? null : highlightedHtml;

  useLayoutEffect(() => {
    const pre = codePreRef.current;
    if (!isStreaming || !pre || isExpanded || !shouldStickToBottomRef.current) return;
    pre.scrollTop = pre.scrollHeight;
  }, [code, isExpanded, isStreaming]);

  const handleCodeScroll = () => {
    const pre = codePreRef.current;
    if (!pre) return;
    const distanceToBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom < 12;
  };

  const copyCode = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }).catch(() => undefined);
  };

  const saveCode = () => {
    if (!onSaveCodeBlock) return;
    saveQueueRef.current.push({ code, language: language || "plaintext" });
    setPendingSaveCount((count) => count + 1);
    if (isSaveQueueRunningRef.current) return;

    isSaveQueueRunningRef.current = true;
    void runCodeBlockSaveQueue(
      saveQueueRef,
      onSaveCodeBlock,
      setSaveState,
      setPendingSaveCount,
    ).finally(() => {
      isSaveQueueRunningRef.current = false;
    });
  };

  if (language.toLowerCase() === "mermaid") {
    return (
      <MarkdownMermaidBlock
        code={code}
        isStreaming={isStreaming}
        onSaveCodeBlock={onSaveCodeBlock}
      />
    );
  }

  return (
    <div className="markdown-preview__code-block">
      <div className="markdown-preview__code-toolbar">
        <span>{language || "text"}</span>
        <div className="markdown-preview__code-actions">
          {canExpand || isExpanded ? (
            <button
              type="button"
              onPointerDown={(event) => runPointerAction(event, () => setIsExpanded((value) => !value))}
              onClick={(event) => runKeyboardAction(event, () => setIsExpanded((value) => !value))}
            >
              {isExpanded ? "收起" : "展开"}
            </button>
          ) : null}
          {canPreviewHtml ? (
            <button
              type="button"
              onPointerDown={(event) => runPointerAction(event, () => onPreviewHtmlCode?.(code))}
              onClick={(event) => runKeyboardAction(event, () => onPreviewHtmlCode?.(code))}
            >
              预览
            </button>
          ) : null}
          {canSave ? (
            <button
              type="button"
              onPointerDown={(event) => runPointerAction(event, saveCode)}
              onClick={(event) => runKeyboardAction(event, saveCode)}
            >
              {formatSaveStateLabel(saveState, pendingSaveCount, "保存")}
            </button>
          ) : null}
          <button
            type="button"
            onPointerDown={(event) => runPointerAction(event, copyCode)}
            onClick={(event) => runKeyboardAction(event, copyCode)}
          >
            {copied ? "已复制" : "复制"}
          </button>
        </div>
      </div>
      <div className="markdown-preview__code-frame">
        <div
          ref={codePreRef}
          className={[
            "markdown-preview__code-pre",
            renderedHighlightedHtml ? "markdown-preview__code-pre--highlighted" : "",
            isExpanded ? "markdown-preview__code-pre--expanded" : "",
          ].filter(Boolean).join(" ")}
          onScroll={handleCodeScroll}
        >
          {renderedHighlightedHtml ? (
            <div className="markdown-preview__code-highlight" dangerouslySetInnerHTML={{ __html: renderedHighlightedHtml }} />
          ) : (
            <pre className="markdown-preview__code-plain"><code>{code}</code></pre>
          )}
        </div>
        {canExpand ? (
          <button
            className={isExpanded ? "markdown-preview__code-expand-overlay markdown-preview__code-expand-overlay--collapse" : "markdown-preview__code-expand-overlay"}
            type="button"
            aria-label={isExpanded ? "收起代码块" : "展开完整代码块"}
            title={isExpanded ? "收起" : "展开"}
            onPointerDown={(event) => runPointerAction(event, () => setIsExpanded((value) => !value))}
            onClick={(event) => runKeyboardAction(event, () => setIsExpanded((value) => !value))}
          >
            <span
              className={isExpanded ? "markdown-preview__code-expand-caret markdown-preview__code-expand-caret--collapse" : "markdown-preview__code-expand-caret"}
              aria-hidden="true"
            />
          </button>
        ) : null}
      </div>
      {canPreviewLatex ? (
        <LatexCodePreview code={code} />
      ) : null}
    </div>
  );
}

function LatexCodePreview({ code }: { code: string }) {
  const html = renderLatexToHtml(code);
  return (
    <div className="markdown-preview__latex-code-preview">
      <div className="markdown-preview__latex-code-preview-label">PREVIEW</div>
      <div
        className="markdown-preview__latex-code-preview-body"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

function renderLatexToHtml(code: string) {
  const normalized = normalizeLatexForKatex(code);
  if (!normalized) return "";
  try {
    return katex.renderToString(normalized, {
      displayMode: true,
      errorColor: "#d88f86",
      throwOnError: false,
    });
  } catch {
    return `<pre>${escapeHtml(normalized)}</pre>`;
  }
}

function useHighlightedCode(
  code: string,
  language: string,
  themeName: string,
  enabled: boolean,
) {
  const shouldUseCache = enabled && code.trim().length > 0 && code.length <= MAX_HIGHLIGHTED_CODE_CHARS;
  const cacheKey = shouldUseCache ? makeHighlightCacheKey(code, language, themeName) : null;
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(() =>
    cacheKey ? getCachedHighlightedCode(cacheKey) ?? null : null,
  );
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    if (!enabled) {
      setHighlightedHtml(null);
      return undefined;
    }
    if (!code.trim()) {
      setHighlightedHtml(null);
      return undefined;
    }
    const cachedHtml = cacheKey ? getCachedHighlightedCode(cacheKey) : undefined;
    if (cachedHtml !== undefined) {
      setHighlightedHtml(cachedHtml);
      return undefined;
    }
    setHighlightedHtml(null);

    const timer = window.setTimeout(() => {
      void import("../model/codeHighlighter").then(({ highlightCodeToHtml }) =>
        highlightCodeToHtml(code, language || "text", themeName),
      ).then((html) => {
        if (cacheKey) {
          setCachedHighlightedCode(cacheKey, html);
        }
        if (requestId === requestIdRef.current) {
          setHighlightedHtml(html);
        }
      }).catch(() => {
        if (requestId === requestIdRef.current) {
          setHighlightedHtml(null);
        }
      });
    }, 80);

    return () => {
      window.clearTimeout(timer);
    };
  }, [cacheKey, code, enabled, language, themeName]);

  return highlightedHtml;
}

function getCachedHighlightedCode(cacheKey: string) {
  const cachedHtml = highlightedCodeCache.get(cacheKey);
  if (cachedHtml === undefined) return undefined;

  highlightedCodeCache.delete(cacheKey);
  highlightedCodeCache.set(cacheKey, cachedHtml);
  return cachedHtml;
}

function setCachedHighlightedCode(cacheKey: string, html: string) {
  if (highlightedCodeCache.has(cacheKey)) {
    highlightedCodeCache.delete(cacheKey);
  }
  highlightedCodeCache.set(cacheKey, html);

  while (highlightedCodeCache.size > MAX_HIGHLIGHT_CACHE_ENTRIES) {
    const oldestCacheKey = highlightedCodeCache.keys().next().value;
    if (oldestCacheKey === undefined) break;
    highlightedCodeCache.delete(oldestCacheKey);
  }
}

function makeHighlightCacheKey(
  code: string,
  language: string,
  themeName: string,
) {
  return `${themeName}\u0000${language.trim().toLowerCase()}\u0000${code}`;
}

function getCodeHighlightThemeName(): string {
  const configuredTheme = document.documentElement.dataset.themeShiki?.trim();
  if (configuredTheme) return configuredTheme;
  return document.documentElement.dataset.themeMode === "light"
    ? "github-light"
    : "github-dark-default";
}

function getCodeLanguage(className: string | undefined) {
  const match = /language-([A-Za-z0-9_-]+)/.exec(className ?? "");
  return match?.[1] ?? "";
}

function isHtmlLanguage(language: string) {
  const normalized = language.toLowerCase();
  return normalized === "html" || normalized === "htm" || normalized === "xhtml";
}

function isLatexLanguage(language: string) {
  const normalized = language.trim().toLowerCase();
  return normalized === "latex" || normalized === "tex" || normalized === "math";
}

function shouldHighlightCode(language: string) {
  const normalized = language.trim().toLowerCase();
  return !["", "text", "txt", "plaintext", "plain"].includes(normalized);
}

function shouldOfferCodeExpand(code: string) {
  return code.length > 1200 || code.split("\n").length > 16;
}

function reactNodeToText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactNodeToText).join("");
  if (isValidElement(node)) {
    return reactNodeToText((node as ReactElement<{ children?: ReactNode }>).props.children);
  }
  return "";
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
