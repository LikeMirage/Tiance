import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState,
  type Dispatch, type ReactNode, type RefObject, type SetStateAction,
} from "react";

type ReadingValues = Map<string, unknown>;
const ReadingContext = createContext<ReadingValues | null>(null);

/** Small UI state owned by open tabs. It never contains document bodies or selections. */
export function DocumentReadingStateProvider({ activeKey, openKeys, children }: {
  activeKey: string; openKeys: string[]; children: ReactNode;
}) {
  const tabs = useRef(new Map<string, ReadingValues>());
  if (!tabs.current.has(activeKey)) tabs.current.set(activeKey, new Map());
  useEffect(() => {
    const open = new Set(openKeys);
    for (const key of tabs.current.keys()) if (!open.has(key)) tabs.current.delete(key);
  }, [openKeys]);
  return <ReadingContext.Provider key={activeKey} value={tabs.current.get(activeKey)!}>
    {children}
  </ReadingContext.Provider>;
}

function useReadingValues() {
  const context = useContext(ReadingContext);
  const fallback = useRef<ReadingValues>(new Map());
  return context ?? fallback.current;
}

export function useDocumentReadingValue<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const values = useReadingValues();
  const [value, setValue] = useState<T>(() => values.has(key) ? values.get(key) as T : initial);
  const update = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    setValue((previous) => {
      const result = typeof next === "function" ? (next as (old: T) => T)(previous) : next;
      values.set(key, result);
      return result;
    });
  }, [key, values]);
  return [value, update];
}

type ScrollPosition = { top: number; left: number; anchor?: string; offset?: number };
const ANCHORS = "h1,h2,h3,h4,h5,h6,p,tr";

/** Restore only after a new rendering is ready; loading/collapsed DOM must not erase progress. */
export function useDocumentReadingScroll(
  key: string, ref: RefObject<HTMLElement | null>, ready: boolean, revision?: unknown,
) {
  const values = useReadingValues();
  const readyRef = useRef(ready);
  readyRef.current = ready;
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !ready) return;
    let restoring = true;
    let frame = 0;
    let captureFrame = 0;
    let saved = values.get(`scroll:${key}`) as ScrollPosition | undefined;
    const restore = () => {
      if (!saved || !restoring) return;
      let top = saved.top;
      if (saved.anchor) {
        let distance = Infinity;
        const containerTop = element.getBoundingClientRect().top;
        for (const node of element.querySelectorAll<HTMLElement>(ANCHORS)) {
          if (node.textContent?.trim().slice(0, 160) !== saved.anchor) continue;
          const candidate = element.scrollTop + node.getBoundingClientRect().top
            - containerTop - (saved.offset ?? 0);
          if (Math.abs(candidate - saved.top) < distance) {
            top = candidate;
            distance = Math.abs(candidate - saved.top);
          }
        }
      }
      element.scrollTop = top;
      element.scrollLeft = saved.left;
    };
    const capture = () => {
      if (!readyRef.current || restoring) return;
      const box = element.getBoundingClientRect();
      const node = element.ownerDocument.elementFromPoint(box.left + Math.min(80, box.width / 2), box.top + 8)
        ?.closest<HTMLElement>(ANCHORS);
      const anchor = node && element.contains(node) ? node : null;
      saved = {
        top: element.scrollTop, left: element.scrollLeft,
        anchor: anchor?.textContent?.trim().slice(0, 160),
        offset: anchor ? anchor.getBoundingClientRect().top - box.top : undefined,
      };
      values.set(`scroll:${key}`, saved);
    };
    const onScroll = () => {
      cancelAnimationFrame(captureFrame);
      captureFrame = requestAnimationFrame(capture);
    };
    // Allow delayed images/layout to settle until the user starts navigating.
    const onIntent = () => { restoring = false; };
    restore();
    frame = requestAnimationFrame(restore);
    const observer = new ResizeObserver(restore);
    const observeContent = () => {
      observer.disconnect();
      observer.observe(element);
      for (const child of element.children) observer.observe(child);
      restore();
    };
    observeContent();
    // Lazy renderers can replace the loading placeholder after this effect runs.
    const childrenObserver = new MutationObserver(observeContent);
    childrenObserver.observe(element, { childList: true });
    const onLoad = () => restore();
    element.addEventListener("load", onLoad, true);
    element.addEventListener("scroll", onScroll, { passive: true });
    element.addEventListener("wheel", onIntent, { passive: true });
    element.ownerDocument.addEventListener("pointerdown", onIntent, true);
    element.ownerDocument.addEventListener("keydown", onIntent, true);
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(captureFrame);
      observer.disconnect();
      childrenObserver.disconnect();
      element.removeEventListener("load", onLoad, true);
      element.removeEventListener("scroll", onScroll);
      element.removeEventListener("wheel", onIntent);
      element.ownerDocument.removeEventListener("pointerdown", onIntent, true);
      element.ownerDocument.removeEventListener("keydown", onIntent, true);
    };
  }, [key, ready, ref, revision, values]);
}
