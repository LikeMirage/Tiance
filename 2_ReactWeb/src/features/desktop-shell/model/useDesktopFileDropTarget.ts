import { useEffect, useRef, useState } from "react";

import {
  DesktopFileDropCoordinator,
  type DesktopFileDropEvent,
  subscribeNativeDesktopFileDrops,
} from "./desktopFileDropBridge";

const DROP_TARGET_ATTRIBUTE = "data-tiance-file-drop-target";
const DROP_ID_EVENT_FIELD = "__tianceNativeFileDropId";
const BUFFERED_NATIVE_FILE_DROP_LIFETIME_MS = 1_000;
const NATIVE_FILE_DROP_TIMEOUT_MS = 2_000;

type NativeFileDropEvent = DragEvent & {
  [DROP_ID_EVENT_FIELD]?: unknown;
};

type UseDesktopFileDropTargetOptions = {
  enabled?: boolean;
  onFileDrop?: (event: DesktopFileDropEvent) => void;
  scopeKey?: string | null;
};

let nextDropTargetId = 0;

export function useDesktopFileDropTarget<T extends HTMLElement = HTMLElement>({
  enabled = true,
  onFileDrop,
  scopeKey,
}: UseDesktopFileDropTargetOptions) {
  const targetRef = useRef<T>(null);
  const targetIdRef = useRef(createDropTargetId());
  const onFileDropRef = useRef(onFileDrop);
  const [isFileDragOver, setIsFileDragOver] = useState(false);
  onFileDropRef.current = onFileDrop;

  const coordinatorRef = useRef<DesktopFileDropCoordinator | null>(null);
  if (coordinatorRef.current === null) {
    coordinatorRef.current = new DesktopFileDropCoordinator({
      bufferLifetimeMs: BUFFERED_NATIVE_FILE_DROP_LIFETIME_MS,
      onFileDrop: (event) => {
        setIsFileDragOver(false);
        onFileDropRef.current?.(event);
      },
      targetId: targetIdRef.current,
      waitTimeoutMs: NATIVE_FILE_DROP_TIMEOUT_MS,
    });
  }

  useEffect(() => {
    const coordinator = coordinatorRef.current;
    if (!coordinator) return;
    const unsubscribe = subscribeNativeDesktopFileDrops((drop) => {
      coordinator.receiveNativeDrop(drop);
    });
    return () => {
      unsubscribe();
      coordinator.reset();
    };
  }, []);

  useEffect(() => {
    const target = targetRef.current;
    const coordinator = coordinatorRef.current;
    if (!enabled || !target || !coordinator) return;

    const targetId = targetIdRef.current;
    target.setAttribute(DROP_TARGET_ATTRIBUTE, targetId);

    const handleDragEnter = (event: DragEvent) => {
      if (!hasExternalFiles(event)) return;
      event.preventDefault();
      setIsFileDragOver(true);
    };
    const handleDragOver = (event: DragEvent) => {
      if (!hasExternalFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      setIsFileDragOver(true);
    };
    const handleDragLeave = (event: DragEvent) => {
      if (event.relatedTarget instanceof Node && target.contains(event.relatedTarget)) return;
      setIsFileDragOver(false);
    };
    const handleDrop = (event: DragEvent) => {
      if (!hasExternalFiles(event)) return;
      event.preventDefault();
      setIsFileDragOver(false);
      coordinator.beginTargetDrop(readDropId(event));
    };

    target.addEventListener("dragenter", handleDragEnter);
    target.addEventListener("dragover", handleDragOver);
    target.addEventListener("dragleave", handleDragLeave);
    target.addEventListener("drop", handleDrop);
    return () => {
      target.removeEventListener("dragenter", handleDragEnter);
      target.removeEventListener("dragover", handleDragOver);
      target.removeEventListener("dragleave", handleDragLeave);
      target.removeEventListener("drop", handleDrop);
      if (target.getAttribute(DROP_TARGET_ATTRIBUTE) === targetId) {
        target.removeAttribute(DROP_TARGET_ATTRIBUTE);
      }
    };
  }, [enabled]);

  useEffect(() => {
    coordinatorRef.current?.reset();
    setIsFileDragOver(false);
  }, [enabled, scopeKey]);

  return { isFileDragOver, targetRef };
}

function createDropTargetId() {
  nextDropTargetId += 1;
  return `tiance-file-drop-target-${nextDropTargetId}`;
}

function hasExternalFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function readDropId(event: DragEvent): string | null {
  const value = (event as NativeFileDropEvent)[DROP_ID_EVENT_FIELD];
  return typeof value === "string" && value.trim() ? value : null;
}
