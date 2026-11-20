import { PaintBrush } from "@phosphor-icons/react";
import { useEffect, useSyncExternalStore } from "react";
import { editorBrowser } from "../../../shared/desktop/editorBrowser";

const preference = "tiance.editorWeb.adaptAppearance";
const changed = "tiance-editor-web-appearance";

function subscribe(notify: () => void) {
  window.addEventListener(changed, notify);
  window.addEventListener("storage", notify);
  window.addEventListener("pywebviewready", notify);
  return () => {
    window.removeEventListener(changed, notify);
    window.removeEventListener("storage", notify);
    window.removeEventListener("pywebviewready", notify);
  };
}

function readPalette() {
  const style = getComputedStyle(document.documentElement);
  // Resolve CSS theme colors before passing them to a separate web document.
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  function color(token: string, fallback: string, keepAlpha = false) {
    if (!ctx) return fallback;
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = fallback;
    ctx.fillStyle = style.getPropertyValue(token).trim();
    ctx.fillRect(0, 0, 1, 1);
    const a = ctx.getImageData(0, 0, 1, 1).data[3];
    if (!a) return keepAlpha ? "#00000000" : fallback;
    if (a < 255) {
      // Sample the opaque color separately to avoid premultiplied-alpha rounding.
      ctx.fillStyle = `rgb(from ${ctx.fillStyle} r g b / 1)`;
      ctx.fillRect(0, 0, 1, 1);
    }
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return "#" + (keepAlpha ? [r, g, b, a] : [r, g, b]).map(n => n.toString(16).padStart(2, "0")).join("");
  }
  const light = document.documentElement.dataset.themeMode === "light";
  return {
    background: color("--color-surface-canvas", color("--app-background-base", light ? "#f8f9fa" : "#1e1e1e")),
    text: color("--color-text-primary", light ? "#202124" : "#f3f4f7"),
    accent: color("--color-accent", light ? "#285ca0" : "#dea059"),
    scrollbarSize: style.getPropertyValue("--scrollbar-size").trim(),
    scrollbarTrack: color("--scrollbar-track", "#00000000", true),
    scrollbarThumb: color("--scrollbar-thumb", "#80808059", true),
    scrollbarThumbHover: color("--scrollbar-thumb-hover", "#80808080", true),
  };
}

export function EditorWebAppearance({ onError }: { onError: (message: string) => void }) {
  const enabled = useSyncExternalStore(subscribe, () => localStorage.getItem(preference) !== "off");
  const available = useSyncExternalStore(subscribe, () => Boolean(window.pywebview?.api?.editor_web_appearance));
  useEffect(() => {
    if (!available) return;
    let active = true;
    function apply() {
      const mode = document.documentElement.dataset.themeMode === "light" ? "light" : "dark";
      void editorBrowser.appearance(enabled ? mode : "original", readPalette()).catch(() => {
        if (active) onError("未能更新网页外观");
      });
    }
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-theme-mode"] });
    return () => { active = false; observer.disconnect(); };
  }, [available, enabled, onError]);

  const title = available ? (enabled ? "网页外观：天策适配，点击恢复网站原貌" : "网页外观：网站原貌，点击启用天策适配")
    : "重启天策后可设置网页外观";
  return <button type="button" className="editor-web__appearance" aria-label="天策网页适配" title={title}
    aria-pressed={enabled && available} disabled={!available} onClick={() => {
      localStorage.setItem(preference, enabled ? "off" : "on");
      window.dispatchEvent(new Event(changed));
    }}><PaintBrush /></button>;
}
