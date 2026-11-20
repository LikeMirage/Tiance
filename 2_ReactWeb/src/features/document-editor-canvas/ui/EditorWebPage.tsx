import { ArrowClockwise, ArrowLeft, ArrowRight, GlobeSimple } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { editorBrowser, normalizeWebAddress, watchEditorWebState } from "../../../shared/desktop/editorBrowser";
import type { EditorWebState } from "../../../shared/types/desktopShell";
import { EditorWebHome } from "./EditorWebHome";
import { EditorWebAppearance } from "./EditorWebAppearance";
import { EditorWebHistory } from "./EditorWebHistory";
import { isWebHomeTab } from "../../document-tabs/model/workspaceTabEntries";
import "./editor-web-page.css";

type Props = {
  tab: DocumentTab;
  workspaceRoot: string;
  onOpenFile: (path: string) => Promise<void>;
  visible: boolean;
  onOpenWebTab: (url: string) => void;
  onSelectHome: () => void;
  onChange: (id: string, url: string, title: string, favicon?: string) => void;
};

export function EditorWebPage({ tab, visible, workspaceRoot, onChange, onOpenWebTab, onSelectHome, onOpenFile }: Props) {
  const id = tab.id;
  const [initialUrl, setInitialUrl] = useState(tab.displayPath);
  const [address, setAddress] = useState(initialUrl);
  const [status, setStatus] = useState<EditorWebState | null>(null);
  const [error, setError] = useState("");
  const previewImage = useRef<HTMLImageElement>(null);
  const editing = useRef(false);
  const surface = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = surface.current;
    const image = previewImage.current;
    if (!node || !image || !visible || !initialUrl) return;
    let disposed = false;
    let frame = 0;
    let previewFrame = 0;
    let lastBounds = "";
    let previewRequest = "";
    let sendingBounds = false;
    let lastPage = "";
    let pending = false;
    function schedule() {
      if (!disposed && !frame) frame = requestAnimationFrame(syncBounds);
    }
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["open", "aria-hidden", "aria-modal", "role", "class", "style"] });
    const resizes = new ResizeObserver(schedule);
    resizes.observe(node);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    document.addEventListener("transitionend", schedule);

    const clearPreview = () => {
      cancelAnimationFrame(previewFrame);
      image.hidden = true;
      image.removeAttribute("src");
    };
    const presentCover = (request: string) => {
      if (disposed || request !== previewRequest) return;
      void editorBrowser.presentCover(id, request).catch(reason => {
        if (!disposed && request === previewRequest) setError(String(reason));
      });
    };
    const preparePreview = async (request: string, imageUrl: string) => {
      if (disposed || !previewRequest || request !== previewRequest) return;
      image.src = imageUrl;
      try {
        await image.decode();
      } catch {
        if (!disposed && request === previewRequest) {
          clearPreview();
          presentCover(request); // The dialog must remain accessible after a failed decode.
        }
        return;
      }
      if (disposed || request !== previewRequest) return;
      image.hidden = false;
      // Allow a host paint with the decoded image before changing native z-order.
      previewFrame = requestAnimationFrame(() => {
        previewFrame = requestAnimationFrame(() => presentCover(request));
      });
    };

    function syncBounds() {
      if (!node || disposed) return;
      frame = 0;
      if (sendingBounds) {
        pending = true;
        return;
      }
      const box = node.getBoundingClientRect();
      const overlays = document.querySelectorAll('dialog[open], [aria-modal="true"], [role="dialog"], [role="menu"], [role="listbox"]');
      const occluded = Array.from(overlays).some(el => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height || el.closest('[aria-hidden="true"]')) return false;
        return el.matches('[aria-modal="true"], :modal') || (r.right > box.left && r.left < box.right && r.bottom > box.top && r.top < box.bottom);
      });
      const w = window.innerWidth, h = window.innerHeight;
      const inPane = box.width > 0 && box.height > 0 && !node.closest('[aria-hidden="true"]');
      const covered = inPane && occluded;
      const shown = inPane && !occluded;
      const edges = shown
        ? [box.left / w, box.top / h, box.right / w, box.bottom / h].map(v => Math.max(0, Math.min(1, v)))
        : null;
      const key = edges ? [...edges, w, h, window.devicePixelRatio].join(",") : covered ? "covered" : "hidden";
      if (key === lastBounds) return;
      lastBounds = key;
      previewRequest = covered ? crypto.randomUUID() : "";
      if (!inPane) clearPreview();
      sendingBounds = true;
      const layout = covered ? editorBrowser.cover(id, previewRequest) : editorBrowser.layout(id, initialUrl, edges, workspaceRoot);
      void layout
        .then(() => { if (!disposed && shown) clearPreview(); })
        .catch(reason => { if (!disposed) setError(String(reason)); })
        .finally(() => {
          sendingBounds = false;
          if (pending) { pending = false; schedule(); }
        });
    }
    const unsubscribe = watchEditorWebState(id, next => {
      setStatus(next);
      const page = JSON.stringify([next.url, next.title, next.favicon]);
      if (page !== lastPage) {
        lastPage = page;
        onChange(id, next.url, next.title, next.favicon);
        if (!editing.current) setAddress(next.url);
      }
    }, preparePreview);
    schedule();
    return () => {
      disposed = true;
      observer.disconnect();
      resizes.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      document.removeEventListener("transitionend", schedule);
      cancelAnimationFrame(frame);
      unsubscribe();
      clearPreview();
      if (lastBounds && lastBounds !== "hidden") void editorBrowser.layout(id, "", null);
    };
  }, [id, visible, initialUrl, onChange, workspaceRoot]);

  function navigate(url: string) {
    setError("");
    if (isWebHomeTab(tab)) {
      onOpenWebTab(url);
      return;
    }
    editing.current = false;
    setAddress(url);
    if (initialUrl || tab.webHomeReturnPage) {
      void editorBrowser.command(id, "navigate", url).catch(reason => setError(String(reason)));
    }
    if (!initialUrl) {
      onChange(id, url, "");
      setInitialUrl(url);
    }
  }

  function goBack() {
    if (!initialUrl && tab.webHomeReturnPage) {
      const { url, title, favicon } = tab.webHomeReturnPage;
      setAddress(url);
      setInitialUrl(url);
      onChange(id, url, title, favicon);
    } else {
      void editorBrowser.command(id, "back");
    }
  }

  return <div className="editor-web" data-tiance-web-scrollbars="">
    <form className="editor-web__bar" aria-label="网页导航" onSubmit={e => {
      e.preventDefault();
      try { navigate(normalizeWebAddress(address)); } catch { setError("请输入有效的 HTTP 或 HTTPS 网址"); }
    }}>
      <button type="button" aria-label="主页" title="Tiance 主页" disabled={isWebHomeTab(tab)} onClick={onSelectHome}><span className="doc-editor__home-icon" aria-hidden="true" /></button>
      <button type="button" aria-label="后退" title="后退" disabled={!status?.back && !tab.webHomeReturnPage} onClick={goBack}><ArrowLeft /></button>
      <button type="button" aria-label="前进" title="前进" disabled={!status?.forward} onClick={() => void editorBrowser.command(id, "forward")}><ArrowRight /></button>
      <button type="button" aria-label="刷新" title="刷新" disabled={!initialUrl} onClick={() => void editorBrowser.command(id, "reload")}><ArrowClockwise /></button>
      <label className="editor-web__address"><GlobeSimple />
        <input aria-label="网页地址" value={address} placeholder="输入网址"
          spellCheck={false} autoComplete="off" onFocus={e => e.target.select()}
          onChange={e => { editing.current = true; setAddress(e.target.value); }}
          onBlur={() => { editing.current = false; }} />
      </label>
      <button type="submit" aria-label="打开网址" title="打开网址"><ArrowRight /></button>
      {visible && <EditorWebAppearance onError={setError} />}
      {visible && <EditorWebHistory onNavigate={navigate} onOpenFile={path => {
        setError("");
        void onOpenFile(path).catch(reason => {
          if (reason?.name !== "AbortError") setError(reason instanceof Error ? reason.message : "无法打开下载文件。");
        });
      }} />}
    </form>
    {(error || status?.error) && <div className="editor-web__error" role="status">{error || status?.error}</div>}
    <div className="editor-web__surface" ref={surface} aria-busy={status?.loading || false}>
      {!initialUrl && <EditorWebHome visible={visible} onNavigate={navigate} />}
      <img className="editor-web__preview" ref={previewImage} alt="" draggable={false} hidden />
    </div>
  </div>;
}
