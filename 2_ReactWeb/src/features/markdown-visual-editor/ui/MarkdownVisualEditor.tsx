import { useEffect, useRef, useState } from "react";
import { Crepe } from "@milkdown/crepe";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/frame-dark.css";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { markdownKatexOptions } from "../../markdown-preview/model/markdownMath";
import { renderMarkdownKatex } from "../../markdown-preview/model/markdownKatex";
import {
  createMarkdownVisualEditorSession,
  prepareMarkdownForVisualEditor,
  restoreMarkdownFromVisualEditor,
  type MarkdownVisualEditorSession,
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
  const hasUserEditIntentRef = useRef(false);
  const editorSessionRef = useRef<MarkdownVisualEditorSession | null>(null);
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

  const restoreEditorContent = (content: string) => (
    editorSessionRef.current?.restore(content)
    ?? restoreMarkdownFromVisualEditor(content)
  );

  const flushPendingChange = () => {
    const pendingValue = pendingValueRef.current;
    if (pendingChangeTimerRef.current !== null) {
      window.clearTimeout(pendingChangeTimerRef.current);
      pendingChangeTimerRef.current = null;
    }
    if (pendingValue === null) {
      return restoreEditorContent(lastCommittedValueRef.current);
    }

    pendingValueRef.current = null;
    if (pendingValue !== lastCommittedValueRef.current) {
      lastCommittedValueRef.current = pendingValue;
      onChangeRef.current(restoreEditorContent(pendingValue));
    }
    return restoreEditorContent(pendingValue);
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
    if (!hasUserEditIntentRef.current) {
      pendingValueRef.current = null;
      if (pendingChangeTimerRef.current !== null) {
        window.clearTimeout(pendingChangeTimerRef.current);
        pendingChangeTimerRef.current = null;
      }
      onSaveRef.current?.(latestValueRef.current);
      return;
    }

    const crepe = crepeRef.current;
    const nextEditorValue = crepe?.getMarkdown();
    const nextValue = nextEditorValue === undefined
      ? flushPendingChange()
      : restoreEditorContent(nextEditorValue);
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

  const markUserEditIntent = () => {
    hasUserEditIntentRef.current = true;
  };

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let disposed = false;
    const editorSession = createMarkdownVisualEditorSession(latestValueRef.current);
    const seedValue = editorSession.editorContent;
    editorSessionRef.current = editorSession;
    root.innerHTML = "";
    createdRef.current = false;
    hasUserEditIntentRef.current = false;
    lastCommittedValueRef.current = seedValue;
    setIsEditorReady(false);

    const crepe = new Crepe({
      root,
      defaultValue: seedValue,
      features: {
        [Crepe.Feature.TopBar]: true,
        [Crepe.Feature.AI]: false,
      },
      featureConfigs: {
        [Crepe.Feature.Latex]: {
          katexOptions: markdownKatexOptions,
        },
      },
    });

    crepe.on((listener) => {
      listener.markdownUpdated((_ctx, markdown) => {
        if (disposed) return;
        if (markdown === lastCommittedValueRef.current) return;
        if (!hasUserEditIntentRef.current) {
          pendingValueRef.current = null;
          lastCommittedValueRef.current = markdown;
          return;
        }
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
        return;
      }
      if (isMarkdownEditingKey(event)) markUserEditIntent();
    };
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("button, input, select, textarea, [role='button'], [role='checkbox']")) {
        markUserEditIntent();
      }
    };
    root.addEventListener("keydown", handleKeyDown);
    root.addEventListener("beforeinput", markUserEditIntent, true);
    root.addEventListener("cut", markUserEditIntent, true);
    root.addEventListener("drop", markUserEditIntent, true);
    root.addEventListener("paste", markUserEditIntent, true);
    root.addEventListener("pointerdown", handlePointerDown, true);

    return () => {
      disposed = true;
      root.removeEventListener("keydown", handleKeyDown);
      root.removeEventListener("beforeinput", markUserEditIntent, true);
      root.removeEventListener("cut", markUserEditIntent, true);
      root.removeEventListener("drop", markUserEditIntent, true);
      root.removeEventListener("paste", markUserEditIntent, true);
      root.removeEventListener("pointerdown", handlePointerDown, true);
      flushPendingChange();
      crepeRef.current = null;
      editorSessionRef.current = null;
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

function isMarkdownEditingKey(event: KeyboardEvent) {
  if (event.altKey) return false;
  if (event.ctrlKey || event.metaKey) {
    return ["b", "i", "k", "u", "y", "z"].includes(event.key.toLowerCase());
  }
  return event.key.length === 1
    || event.key === "Backspace"
    || event.key === "Delete"
    || event.key === "Enter"
    || event.key === "Tab";
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

    const rendered = renderMarkdownKatex(code, true);
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
      preview.dataset.mathRenderError = rendered.error ? "true" : "false";
      preview.title = rendered.error ?? "";
      preview.innerHTML = `<div class="markdown-visual-editor__latex-preview-label">PREVIEW</div><div class="markdown-visual-editor__latex-preview-body">${rendered.html}</div>`;
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
