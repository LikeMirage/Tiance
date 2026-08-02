import { useEffect, useId, useRef, useState } from "react";

import type { CodeBlockSavePayload } from "../model/codeBlockFile";
import {
  copySvgAsPng,
  ensureSvgXmlns,
  formatSaveStateLabel,
  runCodeBlockSaveQueue,
  runKeyboardAction,
  runPointerAction,
  type SaveState,
} from "./markdownCodeBlockActions";

type MermaidThemeName = "default" | "neutral" | "dark" | "forest";

export function MarkdownMermaidBlock({
  code,
  isStreaming,
  onSaveCodeBlock,
}: {
  code: string;
  isStreaming: boolean;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
}) {
  const renderId = useId().replace(/:/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [imageSaveState, setImageSaveState] = useState<SaveState>("idle");
  const [pendingSourceSaveCount, setPendingSourceSaveCount] = useState(0);
  const [pendingImageSaveCount, setPendingImageSaveCount] = useState(0);
  const [copyImageState, setCopyImageState] = useState<"idle" | "copied" | "error">("idle");
  const [isViewerOpen, setIsViewerOpen] = useState(false);
  const [viewerScale, setViewerScale] = useState(1);
  const diagramRef = useRef<HTMLDivElement>(null);
  const sourceSaveQueueRef = useRef<CodeBlockSavePayload[]>([]);
  const imageSaveQueueRef = useRef<CodeBlockSavePayload[]>([]);
  const isSourceSaveQueueRunningRef = useRef(false);
  const isImageSaveQueueRunningRef = useRef(false);

  useEffect(() => {
    let disposed = false;
    if (isStreaming) {
      setSvg("");
      setError("");
      return undefined;
    }
    if (!code.trim()) {
      setSvg("");
      setError("");
      return undefined;
    }
    const timer = window.setTimeout(() => {
      void import("mermaid").then(async ({ default: mermaid }) => {
        const mermaidTheme = getMermaidThemeName();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: mermaidTheme,
          themeVariables: getMermaidThemeVariables(mermaidTheme),
        });
        await mermaid.parse(code);

        const measureEl = document.createElement("div");
        const measuredWidth = diagramRef.current?.getBoundingClientRect().width ?? 0;
        measureEl.style.position = "absolute";
        measureEl.style.left = "-9999px";
        measureEl.style.top = "-9999px";
        measureEl.style.width = `${Math.max(320, measuredWidth || 720)}px`;
        document.body.appendChild(measureEl);
        try {
          return await mermaid.render(`markdown-preview-mermaid-${renderId}`, code, measureEl);
        } finally {
          document.body.removeChild(measureEl);
        }
      }).then((result) => {
        if (disposed) return;
        setSvg(result.svg.replace(/translate\(undefined,\s*NaN\)/g, "translate(0, 0)"));
        setError("");
      }).catch((err: unknown) => {
        if (disposed) return;
        setSvg("");
        setError(err instanceof Error ? err.message : "Mermaid 渲染失败");
      });
    }, 120);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [code, isStreaming, renderId]);

  const saveCode = () => {
    if (!onSaveCodeBlock) return;
    sourceSaveQueueRef.current.push({ code, language: "mermaid" });
    setPendingSourceSaveCount((count) => count + 1);
    if (isSourceSaveQueueRunningRef.current) return;

    isSourceSaveQueueRunningRef.current = true;
    void runCodeBlockSaveQueue(
      sourceSaveQueueRef,
      onSaveCodeBlock,
      setSaveState,
      setPendingSourceSaveCount,
    ).finally(() => {
      isSourceSaveQueueRunningRef.current = false;
    });
  };

  const saveImage = () => {
    if (!onSaveCodeBlock || !svg) return;
    imageSaveQueueRef.current.push({ code: ensureSvgXmlns(svg), language: "svg" });
    setPendingImageSaveCount((count) => count + 1);
    if (isImageSaveQueueRunningRef.current) return;

    isImageSaveQueueRunningRef.current = true;
    void runCodeBlockSaveQueue(
      imageSaveQueueRef,
      onSaveCodeBlock,
      setImageSaveState,
      setPendingImageSaveCount,
    ).finally(() => {
      isImageSaveQueueRunningRef.current = false;
    });
  };

  const copyImage = () => {
    if (!svg) return;
    void copySvgAsPng(svg).then(() => {
      setCopyImageState("copied");
      window.setTimeout(() => setCopyImageState("idle"), 1400);
    }).catch(() => {
      void navigator.clipboard.writeText(ensureSvgXmlns(svg)).then(() => {
        setCopyImageState("copied");
        window.setTimeout(() => setCopyImageState("idle"), 1400);
      }).catch(() => {
        setCopyImageState("error");
        window.setTimeout(() => setCopyImageState("idle"), 1800);
      });
    });
  };

  return (
    <div className="markdown-preview__code-block markdown-preview__mermaid-block">
      <div className="markdown-preview__code-toolbar">
        <span>mermaid</span>
        <div className="markdown-preview__code-actions">
          {svg ? (
            <>
              <button
                type="button"
                onPointerDown={(event) => runPointerAction(event, () => setIsViewerOpen(true))}
                onClick={(event) => runKeyboardAction(event, () => setIsViewerOpen(true))}
              >
                查看
              </button>
              <button
                type="button"
                onPointerDown={(event) => runPointerAction(event, copyImage)}
                onClick={(event) => runKeyboardAction(event, copyImage)}
              >
                {copyImageState === "copied" ? "已复制" : copyImageState === "error" ? "失败" : "复制图"}
              </button>
            </>
          ) : null}
          {svg && onSaveCodeBlock ? (
            <button
              type="button"
              onPointerDown={(event) => runPointerAction(event, saveImage)}
              onClick={(event) => runKeyboardAction(event, saveImage)}
            >
              {formatSaveStateLabel(imageSaveState, pendingImageSaveCount, "保存图")}
            </button>
          ) : null}
          {onSaveCodeBlock ? (
            <button
              type="button"
              onPointerDown={(event) => runPointerAction(event, saveCode)}
              onClick={(event) => runKeyboardAction(event, saveCode)}
            >
              {formatSaveStateLabel(saveState, pendingSourceSaveCount, "保存源码")}
            </button>
          ) : null}
        </div>
      </div>
      {svg ? (
        <div ref={diagramRef} className="markdown-preview__mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <pre className="markdown-preview__code-pre markdown-preview__code-pre--expanded">
          <code>{error || code}</code>
        </pre>
      )}
      {isViewerOpen ? (
        <div
          className="markdown-preview__mermaid-viewer"
          role="dialog"
          aria-modal="true"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) {
              setIsViewerOpen(false);
            }
          }}
        >
          <div className="markdown-preview__mermaid-viewer-panel">
            <div className="markdown-preview__mermaid-viewer-toolbar">
              <span>mermaid</span>
              <div className="markdown-preview__code-actions">
                <button type="button" onPointerDown={(event) => runPointerAction(event, () => setViewerScale((value) => Math.max(0.35, value - 0.15)))} onClick={(event) => runKeyboardAction(event, () => setViewerScale((value) => Math.max(0.35, value - 0.15)))}>
                  缩小
                </button>
                <button type="button" onPointerDown={(event) => runPointerAction(event, () => setViewerScale(1))} onClick={(event) => runKeyboardAction(event, () => setViewerScale(1))}>
                  100%
                </button>
                <button type="button" onPointerDown={(event) => runPointerAction(event, () => setViewerScale((value) => Math.min(3, value + 0.15)))} onClick={(event) => runKeyboardAction(event, () => setViewerScale((value) => Math.min(3, value + 0.15)))}>
                  放大
                </button>
                <button type="button" onPointerDown={(event) => runPointerAction(event, copyImage)} onClick={(event) => runKeyboardAction(event, copyImage)}>
                  {copyImageState === "copied" ? "已复制" : copyImageState === "error" ? "失败" : "复制图"}
                </button>
                {onSaveCodeBlock ? (
                  <>
                    <button type="button" onPointerDown={(event) => runPointerAction(event, saveImage)} onClick={(event) => runKeyboardAction(event, saveImage)}>
                      {formatSaveStateLabel(imageSaveState, pendingImageSaveCount, "保存图")}
                    </button>
                    <button type="button" onPointerDown={(event) => runPointerAction(event, saveCode)} onClick={(event) => runKeyboardAction(event, saveCode)}>
                      {formatSaveStateLabel(saveState, pendingSourceSaveCount, "保存源码")}
                    </button>
                  </>
                ) : null}
                <button type="button" onPointerDown={(event) => runPointerAction(event, () => setIsViewerOpen(false))} onClick={(event) => runKeyboardAction(event, () => setIsViewerOpen(false))}>
                  关闭
                </button>
              </div>
            </div>
            <div className="markdown-preview__mermaid-viewer-body">
              <div
                className="markdown-preview__mermaid-viewer-canvas"
                style={{ transform: `scale(${viewerScale})` }}
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function getMermaidThemeName(): MermaidThemeName {
  const configuredTheme = document.documentElement.dataset.themeMermaid?.trim();
  if (
    configuredTheme === "default" ||
    configuredTheme === "neutral" ||
    configuredTheme === "dark" ||
    configuredTheme === "forest"
  ) {
    return configuredTheme;
  }
  return document.documentElement.dataset.themeMode === "light" ? "default" : "dark";
}

function getMermaidThemeVariables(theme: MermaidThemeName) {
  if (theme === "dark") {
    return {
      background: "transparent",
      primaryColor: "#242424",
      primaryTextColor: "#dadada",
      lineColor: "#9c9c9c",
    };
  }

  return {
    background: "transparent",
    primaryColor: "#f8fafc",
    primaryTextColor: "#0f172a",
    lineColor: "#64748b",
  };
}
