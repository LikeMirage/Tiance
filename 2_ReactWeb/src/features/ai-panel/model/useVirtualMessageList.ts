import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type RefObject,
} from "react";

import type { ChatMessage } from "./chatMessage";

type UseVirtualMessageListOptions = {
  enabled: boolean;
  estimateSize?: number;
  messages: ChatMessage[];
  overscanPx?: number;
  scrollParentRef: RefObject<HTMLDivElement | null>;
  sizeCacheRef?: MutableRefObject<Map<string, number>>;
};

export type VirtualMessageItem = {
  index: number;
  key: string;
  message: ChatMessage;
  size: number;
  start: number;
};

const DEFAULT_ESTIMATE_SIZE = 140;
const DEFAULT_OVERSCAN_PX = 720;

export function useVirtualMessageList({
  enabled,
  estimateSize = DEFAULT_ESTIMATE_SIZE,
  messages,
  overscanPx = DEFAULT_OVERSCAN_PX,
  scrollParentRef,
  sizeCacheRef,
}: UseVirtualMessageListOptions) {
  const listRef = useRef<HTMLDivElement>(null);
  const internalSizeCacheRef = useRef(new Map<string, number>());
  const heightsRef = sizeCacheRef ?? internalSizeCacheRef;
  const offsetsRef = useRef<number[]>([0]);
  const contentTopRef = useRef(0);
  const viewportRef = useRef({ height: 0, scrollTop: 0 });
  const [measureVersion, setMeasureVersion] = useState(0);
  const [viewport, setViewport] = useState({ height: 0, scrollTop: 0 });

  const updateViewport = useCallback(() => {
    const scrollEl = scrollParentRef.current;
    const listEl = listRef.current;
    if (!scrollEl || !listEl) return;

    const parentRect = scrollEl.getBoundingClientRect();
    const listRect = listEl.getBoundingClientRect();
    const contentTop = listRect.top - parentRect.top + scrollEl.scrollTop;
    const nextViewport = {
      height: scrollEl.clientHeight,
      scrollTop: scrollEl.scrollTop,
    };

    contentTopRef.current = contentTop;
    viewportRef.current = nextViewport;
    setViewport((previous) =>
      previous.height === nextViewport.height &&
      previous.scrollTop === nextViewport.scrollTop
        ? previous
        : nextViewport,
    );
  }, [scrollParentRef]);

  useLayoutEffect(() => {
    if (!enabled) return;
    updateViewport();
  }, [enabled, messages.length, updateViewport]);

  useEffect(() => {
    if (!enabled) return undefined;
    const scrollEl = scrollParentRef.current;
    if (!scrollEl) return undefined;

    let frameId: number | null = null;
    const scheduleUpdate = () => {
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        updateViewport();
      });
    };

    const resizeObserver = new ResizeObserver(scheduleUpdate);
    resizeObserver.observe(scrollEl);
    if (listRef.current) {
      resizeObserver.observe(listRef.current);
    }
    scrollEl.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    scheduleUpdate();

    return () => {
      resizeObserver.disconnect();
      scrollEl.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [enabled, scrollParentRef, updateViewport]);

  useEffect(() => {
    if (!enabled || sizeCacheRef) return;
    const messageIds = new Set(messages.map((message) => message.id));
    heightsRef.current.forEach((_, messageId) => {
      if (!messageIds.has(messageId)) {
        heightsRef.current.delete(messageId);
      }
    });
  }, [enabled, heightsRef, messages, sizeCacheRef]);

  const layout = useMemo(() => {
    const offsets = new Array<number>(messages.length + 1);
    offsets[0] = 0;
    messages.forEach((message, index) => {
      offsets[index + 1] =
        offsets[index] + (heightsRef.current.get(message.id) ?? estimateSize);
    });
    offsetsRef.current = offsets;
    return {
      offsets,
      totalSize: offsets[offsets.length - 1] ?? 0,
    };
  }, [estimateSize, measureVersion, messages]);

  const virtualItems = useMemo(() => {
    if (!enabled || messages.length === 0) return [];

    const viewportStart = Math.max(
      0,
      viewport.scrollTop - contentTopRef.current - overscanPx,
    );
    const viewportEnd = Math.min(
      layout.totalSize,
      viewport.scrollTop - contentTopRef.current + viewport.height + overscanPx,
    );
    const startIndex = findFirstVisibleIndex(layout.offsets, viewportStart);
    const endIndex = findLastVisibleIndex(layout.offsets, viewportEnd);
    const items: VirtualMessageItem[] = [];

    for (let index = startIndex; index <= endIndex; index += 1) {
      const message = messages[index];
      if (!message) continue;
      items.push({
        index,
        key: message.id,
        message,
        size: layout.offsets[index + 1] - layout.offsets[index],
        start: layout.offsets[index],
      });
    }

    return items;
  }, [
    enabled,
    layout.offsets,
    layout.totalSize,
    messages,
    overscanPx,
    viewport.height,
    viewport.scrollTop,
  ]);

  const measureMessage = useCallback((
    messageId: string,
    index: number,
    height: number,
  ) => {
    if (!enabled || height <= 0) return;
    const previousHeight = heightsRef.current.get(messageId);
    const nextHeight = Math.ceil(height);
    if (previousHeight === nextHeight) return;

    const scrollEl = scrollParentRef.current;
    const previousEffectiveHeight = previousHeight ?? estimateSize;
    const delta = nextHeight - previousEffectiveHeight;
    const rowBottom = offsetsRef.current[index + 1] ?? 0;
    const viewportStart =
      (scrollEl?.scrollTop ?? viewportRef.current.scrollTop) - contentTopRef.current;

    heightsRef.current.set(messageId, nextHeight);
    setMeasureVersion((version) => version + 1);

    if (!scrollEl || delta === 0) return;
    if (rowBottom < viewportStart) {
      scrollEl.scrollTop += delta;
      return;
    }
  }, [enabled, estimateSize, scrollParentRef]);

  const scrollToMessage = useCallback((
    messageId: string,
    behavior: ScrollBehavior = "smooth",
  ) => {
    if (!enabled) return false;
    const index = messages.findIndex((message) => message.id === messageId);
    const scrollEl = scrollParentRef.current;
    if (index < 0 || !scrollEl) return false;

    const messageTop = offsetsRef.current[index] ?? 0;
    scrollEl.scrollTo({
      top: Math.max(0, contentTopRef.current + messageTop - 8),
      behavior,
    });
    return true;
  }, [enabled, messages, scrollParentRef]);

  return {
    isVirtualized: enabled,
    listRef,
    measureMessage,
    scrollToMessage,
    totalSize: layout.totalSize,
    virtualItems,
  };
}

function findFirstVisibleIndex(offsets: number[], target: number) {
  let low = 0;
  let high = Math.max(0, offsets.length - 2);
  let result = 0;

  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (offsets[middle + 1] >= target) {
      result = middle;
      high = middle - 1;
    } else {
      low = middle + 1;
    }
  }

  return result;
}

function findLastVisibleIndex(offsets: number[], target: number) {
  let low = 0;
  let high = Math.max(0, offsets.length - 2);
  let result = high;

  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (offsets[middle] <= target) {
      result = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }

  return result;
}
