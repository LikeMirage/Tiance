import { useEffect, useRef, useState } from "react";
import { Crepe } from "@milkdown/crepe";
import katex from "katex";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/frame-dark.css";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import {
  normalizeLatexForKatex,
} from "../../markdown-preview/model/markdownMath";
import {
  prepareMarkdownForVisualEditor,
  restoreMarkdownFromVisualEditor,
} from "../model/markdownVisualEditorContent";
import "./markdown-visual-editor.css";

type MarkdownVisualEditorProps = {
  onChange: (value: string) => void;
  onDirty?: () => void;
  onSave?: (value: string) => void;
  value: string;
};

const CHANGE_COMMIT_DELAY_MS = 220;
const VISUAL_EDITOR_MINIMUM_LOADING_MS = 260;

export function MarkdownVisualEditor({
  onChange,
  onDirty,
  onSave,
  value,
}: MarkdownVisualEditorProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const crepeRef = useRef<Crepe | null>(null);
  const createdRef = useRef(false);
  const pendingChangeTimerRef = useRef<number | null>(null);
  const pendingValueRef = useRef<string | null>(null);
  const lastCommittedValueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  const onDirtyRef = useRef(onDirty);
  const onSaveRef = useRef(onSave);
  const latestValueRef = useRef(value);
  const [reloadKey, setReloadKey] = useState(0);
  const [isEditorReady, setIsEditorReady] = useState(false);
  const isEditorLoadingVisible = useMinimumLoading(
    !isEditorReady,
    VISUAL_EDITOR_MINIMUM_LOADING_MS,
  );

  onChangeRef.current = onChange;
  onDirtyRef.current = onDirty;
  onSaveRef.current = onSave;
  latestValueRef.current = value;

  const flushPendingChange = () => {
    const pendingValue = pendingValueRef.current;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
      pendingChangeTimerRef.current = null;
    }
    if (pendingValue === null) {
      return restoreMarkdownFromVisualEditor(lastCommittedValueRef.current);
    }

    pendingValueRef.current = null;
    if (pendingValue !== lastCommittedValueRef.current) {
      lastCommittedValueRef.current = pendingValue;
      onChangeRef.current(restoreMarkdownFromVisualEditor(pendingValue));
    }
    return restoreMarkdownFromVisualEditor(pendingValue);
  };

  const scheduleChangeCommit = (nextValue: string) => {
    pendingValueRef.current = nextValue;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
    }
    pendingChangeTimerRef.current = window.setTimeout(() => {
      flushPendingChange();
    }, CHANGE_COMMIT_DELAY_MS);
  };

  const saveCurrentDocument = () => {
    const crepe = crepeRef.current;
    const nextEditorValue = crepe?.getMarkdown();
    const nextValue = nextEditorValue === undefined
      ? flushPendingChange()
      : restoreMarkdownFromVisualEditor(nextEditorValue);
    pendingValueRef.current = null;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
      pendingChangeTimerRef.current = null;
    }
    if (nextEditorValue !== undefined && nextEditorValue !== lastCommittedValueRef.current) {
      lastCommittedValueRef.current = nextEditorValue;
      onChangeRef.current(nextValue);
    }
    onSaveRef.current?.(nextValue);
  };

  const commitEditorChange = (nextValue: string) => {
    const normalizedCurrentValue = prepareMarkdownForVisualEditor(latestValueRef.current);
    if (nextValue === normalizedCurrentValue) {
      pendingValueRef.current = null;
      lastCommittedValueRef.current = nextValue;
      return;
    }

    onDirtyRef.current?.();
    scheduleChangeCommit(nextValue);
  };

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let disposed = false;
    const seedValue = prepareMarkdownForVisualEditor(latestValueRef.current);
    root.innerHTML = "";
    createdRef.current = false;
    setIsEditorReady(false);

    const crepe = new Crepe({
      root,
      defaultValue: seedValue,
      features: {
        [Crepe.Feature.TopBar]: true,
        [Crepe.Feature.AI]: false,
      },
    });

    crepe.on((listener) => {
      listener.markdownUpdated((_ctx, markdown) => {
        if (disposed) return;
        if (markdown === lastCommittedValueRef.current) return;
        commitEditorChange(markdown);
      });
      listener.blur(() => {
        flushPendingChange();
      });
    });

    void crepe.create().then(() => {
      if (disposed) {
        void crepe.destroy();
        return;
      }
      crepeRef.current = crepe;
      createdRef.current = true;
      lastCommittedValueRef.current = seedValue;
      setIsEditorReady(true);
      if (prepareMarkdownForVisualEditor(latestValueRef.current) !== seedValue) {
        setReloadKey((key) => key + 1);
      }
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveCurrentDocument();
      }
    };
    root.addEventListener("keydown", handleKeyDown);

    return () => {
      disposed = true;
      root.removeEventListener("keydown", handleKeyDown);
      flushPendingChange();
      crepeRef.current = null;
      createdRef.current = false;
      void crepe.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  useEffect(() => {
    if (!createdRef.current) return;
    const nextValue = prepareMarkdownForVisualEditor(value);
    const currentValue = pendingValueRef.current ?? lastCommittedValueRef.current;
    if (nextValue === currentValue) return;

    pendingValueRef.current = null;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
      pendingChangeTimerRef.current = null;
    }
    lastCommittedValueRef.current = nextValue;
    setReloadKey((key) => key + 1);
  }, [value]);

  useEffect(() => {
    const root = rootRef.current;
    if (!isEditorReady || !root) return undefined;

    renderLatexCodeBlockPreviews(root);
    const observer = new MutationObserver(() => {
      window.requestAnimationFrame(() => renderLatexCodeBlockPreviews(root));
    });
    observer.observe(root, {
      childList: true,
      characterData: true,
      subtree: true,
    });

    return () => observer.disconnect();
  }, [isEditorReady]);

  return (
    <div className="markdown-visual-editor" aria-busy={isEditorLoadingVisible}>
      {isEditorLoadingVisible ? (
        <LoadingStrip
          ariaLabel="正在加载 Markdown 编辑器"
          className="markdown-visual-editor__loading"
          mode="fill"
          visual="ring"
        />
      ) : null}
      <div
        aria-hidden={isEditorLoadingVisible}
        ref={rootRef}
        className={
          !isEditorLoadingVisible
            ? "markdown-visual-editor__root"
            : "markdown-visual-editor__root markdown-visual-editor__root--loading"
        }
      />
    </div>
  );
}

function renderLatexCodeBlockPreviews(root: HTMLElement) {
  const codeBlocks = root.querySelectorAll<HTMLElement>(".milkdown-code-block");
  for (const block of codeBlocks) {
    const language = readCodeBlockLanguage(block);
    if (!isLatexLanguage(language)) {
      removeManagedLatexPreview(block);
      continue;
    }

    const code = readCodeBlockText(block);
    if (!code.trim()) {
      removeManagedLatexPreview(block);
      continue;
    }

    const previewHtml = renderLatexToHtml(code);
    block.dataset.tianceLatexPreview = "true";
    hideNativeLatexPreview(block);
    let preview = block.querySelector<HTMLElement>(":scope > .markdown-visual-editor__latex-preview");
    if (!preview) {
      preview = document.createElement("div");
      preview.className = "markdown-visual-editor__latex-preview";
      block.appendChild(preview);
    }
    if (preview.dataset.source !== code) {
      preview.dataset.source = code;
      preview.innerHTML = `<div class="markdown-visual-editor__latex-preview-label">PREVIEW</div><div class="markdown-visual-editor__latex-preview-body">${previewHtml}</div>`;
    }
  }
}

function readCodeBlockLanguage(block: HTMLElement) {
  const languageButton = block.querySelector<HTMLElement>(".language-button");
  const text = languageButton?.textContent?.trim() ?? "";
  return text;
}

function readCodeBlockText(block: HTMLElement) {
  const lines = block.querySelectorAll<HTMLElement>(".cm-line");
  if (lines.length > 0) {
    return Array.from(lines).map((line) => line.textContent ?? "").join("\n");
  }
  const content = block.querySelector<HTMLElement>(".cm-content");
  return content?.textContent ?? "";
}

function removeManagedLatexPreview(block: HTMLElement) {
  delete block.dataset.tianceLatexPreview;
  for (const previewPanel of Array.from(
    block.querySelectorAll(".preview-panel"),
  )) {
    previewPanel.classList.remove("markdown-visual-editor__native-latex-preview-hidden");
  }
  block.querySelector(":scope > .markdown-visual-editor__latex-preview")?.remove();
}

function hideNativeLatexPreview(block: HTMLElement) {
  for (const previewPanel of Array.from(
    block.querySelectorAll(".preview-panel"),
  )) {
    previewPanel.classList.add("markdown-visual-editor__native-latex-preview-hidden");
  }
}

function isLatexLanguage(language: string) {
  const normalized = language.trim().toLowerCase();
  return normalized === "latex" || normalized === "tex" || normalized === "math";
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

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
