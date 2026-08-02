import type {
  Dispatch,
  MouseEvent,
  MutableRefObject,
  PointerEvent,
  SetStateAction,
} from "react";

import type { CodeBlockSavePayload } from "../model/codeBlockFile";

export type SaveState = "idle" | "saving" | "saved" | "error";

export async function runCodeBlockSaveQueue(
  queueRef: MutableRefObject<CodeBlockSavePayload[]>,
  onSaveCodeBlock: (payload: CodeBlockSavePayload) => Promise<string>,
  setSaveState: Dispatch<SetStateAction<SaveState>>,
  setPendingSaveCount: Dispatch<SetStateAction<number>>,
) {
  let hasError = false;
  setSaveState("saving");

  while (queueRef.current.length > 0) {
    const payload = queueRef.current.shift();
    if (!payload) continue;
    try {
      await onSaveCodeBlock(payload);
    } catch {
      hasError = true;
    } finally {
      setPendingSaveCount((count) => Math.max(0, count - 1));
    }
  }

  setSaveState(hasError ? "error" : "saved");
  window.setTimeout(() => setSaveState("idle"), hasError ? 1800 : 1400);
}

export function formatSaveStateLabel(
  state: SaveState,
  pendingCount: number,
  idleLabel: string,
) {
  if (state === "saving") {
    return pendingCount > 1 ? `保存中 ${pendingCount}` : "保存中";
  }
  if (state === "saved") return "已保存";
  if (state === "error") return "失败";
  return idleLabel;
}

export function runPointerAction(
  event: PointerEvent<HTMLButtonElement>,
  action: () => void,
) {
  if (event.currentTarget.disabled) return;
  event.preventDefault();
  event.stopPropagation();
  action();
}

export function runKeyboardAction(
  event: MouseEvent<HTMLButtonElement>,
  action: () => void,
) {
  event.preventDefault();
  event.stopPropagation();
  if (event.detail === 0) {
    action();
  }
}

export async function copySvgAsPng(svg: string) {
  if (!("ClipboardItem" in window)) {
    throw new Error("当前环境不支持图片剪贴板。");
  }
  const blob = await svgToPngBlob(svg);
  await navigator.clipboard.write([
    new ClipboardItem({ [blob.type]: blob }),
  ]);
}

export function ensureSvgXmlns(svg: string) {
  if (/^<svg[^>]+xmlns=/.test(svg.trim())) return svg;
  return svg.replace(/^<svg\b/, '<svg xmlns="http://www.w3.org/2000/svg"');
}

function svgToPngBlob(svg: string) {
  return new Promise<Blob>((resolve, reject) => {
    const image = new Image();
    const svgBlob = new Blob([ensureSvgXmlns(svg)], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    image.onload = () => {
      const canvas = document.createElement("canvas");
      const width = Math.max(1, image.naturalWidth || image.width || 1200);
      const height = Math.max(1, image.naturalHeight || image.height || 800);
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) {
        URL.revokeObjectURL(url);
        reject(new Error("无法创建图片画布。"));
        return;
      }
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, width, height);
      context.drawImage(image, 0, 0, width, height);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("图片转换失败。"));
        }
      }, "image/png");
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("SVG 图片加载失败。"));
    };
    image.src = url;
  });
}
