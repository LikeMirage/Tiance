import { useEffect, useRef, useState } from "react";

import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type { LoadState, OfficeLoadingVisibilityChange } from "./officePreviewTypes";
import { officePreviewMinimumLoadingMs } from "./officePreviewTypes";

export function WordPreview({
  onLoadingVisibleChange,
  onMissing = null,
  src,
  zoom,
}: {
  onLoadingVisibleChange?: OfficeLoadingVisibilityChange;
  onMissing?: (() => void) | null;
  src: string | null;
  zoom: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const onMissingRef = useRef(onMissing);
  const [state, setState] = useState<LoadState>(() => (src ? "loading" : "idle"));
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const isLoadingVisible = useMinimumLoading(state === "loading", officePreviewMinimumLoadingMs);

  useEffect(() => {
    onLoadingVisibleChange?.(isLoadingVisible);
  }, [isLoadingVisible, onLoadingVisibleChange]);

  useEffect(() => {
    onMissingRef.current = onMissing;
  }, [onMissing]);

  useEffect(() => {
    const container = containerRef.current;
    if (!src || !container) {
      setState("idle");
      setErrorMessage(null);
      return undefined;
    }

    let isCancelled = false;
    const controller = new AbortController();

    const load = async () => {
      setState("loading");
      setErrorMessage(null);
      container.replaceChildren();

      try {
        const response = await fetch(src, { signal: controller.signal });
        if (!response.ok) {
          if (response.status === 404) {
            onMissingRef.current?.();
            return;
          }
          throw new Error(`文件读取失败：${response.status}`);
        }
        const arrayBuffer = await response.arrayBuffer();
        if (isCancelled) return;
        const fingerprint = await sha256Fingerprint(arrayBuffer);
        if (isCancelled) return;
        const { renderAsync } = await import("docx-preview");
        if (isCancelled) return;
        await renderAsync(arrayBuffer, container, undefined, {
          breakPages: true,
          className: "office-docx",
          ignoreFonts: false,
          ignoreHeight: false,
          ignoreLastRenderedPageBreak: false,
          ignoreWidth: false,
          inWrapper: true,
          renderEndnotes: true,
          renderFooters: true,
          renderFootnotes: true,
          renderHeaders: true,
          useBase64URL: true,
        });
        if (isCancelled) return;
        container.dataset.documentFingerprint = fingerprint;
        setState("ready");
      } catch (err) {
        if (isCancelled || controller.signal.aborted) return;
        setState("error");
        setErrorMessage(err instanceof Error ? err.message : "Word 文件预览失败。");
      }
    };

    void load();

    return () => {
      isCancelled = true;
      controller.abort();
      container.replaceChildren();
    };
  }, [src]);

  return (
    <main className="office-preview__body">
      {isLoadingVisible ? (
        <LoadingStrip
          ariaLabel="正在加载 Word 文档"
          mode="fill"
          surface="dark"
          visual="ring"
        />
      ) : null}
      {!isLoadingVisible && state === "error" ? (
        <div className="office-preview__status office-preview__status--error">{errorMessage}</div>
      ) : null}
      <div
        className={isLoadingVisible
          ? "office-preview__scroll office-preview__scroll--loading-hidden"
          : "office-preview__scroll"}
      >
        <div className="office-preview__word" ref={containerRef} style={{ zoom }} />
      </div>
      {!isLoadingVisible && state === "idle" ? <div className="office-preview__empty">Word 文件地址无效。</div> : null}
    </main>
  );
}

async function sha256Fingerprint(value: ArrayBuffer) {
  const digest = await crypto.subtle.digest("SHA-256", value);
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `sha256:${hex}`;
}
