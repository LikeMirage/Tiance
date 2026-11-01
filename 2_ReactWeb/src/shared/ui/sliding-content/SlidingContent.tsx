import { useCallback, useLayoutEffect, useRef, useState, type HTMLAttributes, type Ref } from "react";
import "./sliding-content.css";

export const SLIDE_DURATION_MS = 220;

type Props = HTMLAttributes<HTMLDivElement> & {
  expanded: boolean;
  collapsedHeight?: number;
  ref?: Ref<HTMLDivElement>;
};

/** Keep closing content mounted until its height transition finishes. */
export function SlidingContent({ expanded, collapsedHeight = 0, children, className = "", ref: forwardedRef, ...props }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const animation = useRef<Animation | null>(null);
  const previousExpanded = useRef(expanded);
  const [retained, setRetained] = useState(expanded);
  const initialStyle = useRef({ height: expanded || collapsedHeight > 0 ? "auto" : "0px",
    maxHeight: !expanded && collapsedHeight > 0 ? `${collapsedHeight}px` : undefined });
  const present = expanded || retained || collapsedHeight > 0;
  const setRoot = useCallback((element: HTMLDivElement | null) => {
    root.current = element;
    if (typeof forwardedRef === "function") forwardedRef(element);
    else if (forwardedRef) forwardedRef.current = element;
  }, [forwardedRef]);

  useLayoutEffect(() => {
    const element = root.current;
    const content = inner.current;
    if (!element || !content) return;
    const changed = previousExpanded.current !== expanded;
    previousExpanded.current = expanded;
    const from = element.getBoundingClientRect().height;
    if (animation.current) {
      animation.current.onfinish = null;
      animation.current.cancel();
      animation.current = null;
    }
    element.style.maxHeight = "none";
    const naturalHeight = () => {
      const styles = getComputedStyle(element);
      return content.getBoundingClientRect().height + parseFloat(styles.paddingTop || "0")
        + parseFloat(styles.paddingBottom || "0") + parseFloat(styles.borderTopWidth || "0")
        + parseFloat(styles.borderBottomWidth || "0");
    };
    const settle = () => {
      element.style.height = expanded ? "auto" : `${Math.min(collapsedHeight, naturalHeight())}px`;
      delete element.dataset.sliding;
      setRetained(expanded);
    };
    const to = expanded ? naturalHeight() : Math.min(collapsedHeight, naturalHeight());
    element.style.height = expanded ? "auto" : `${to}px`;
    if (changed && Math.abs(from - to) > 0.5 && typeof element.animate === "function"
      && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      element.dataset.sliding = "true";
      const current = element.animate([{ height: `${from}px` }, { height: `${to}px` }], {
        duration: SLIDE_DURATION_MS, easing: "cubic-bezier(0.2, 0, 0, 1)",
      });
      animation.current = current;
      current.onfinish = () => {
        if (animation.current !== current) return;
        animation.current = null;
        settle();
      };
    } else settle();

    const observer = new ResizeObserver(() => {
      // Once expanded, natural layout follows streaming text without animating
      // every token. Closed previews still grow up to their configured limit.
      if (!expanded && !animation.current) settle();
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [expanded, collapsedHeight]);

  useLayoutEffect(() => () => {
    if (animation.current) {
      animation.current.onfinish = null;
      animation.current.cancel();
    }
  }, []);

  return <div {...props} className={`sliding-content ${className}`} style={{ ...initialStyle.current, ...props.style }}
    aria-hidden={!expanded && collapsedHeight === 0 || undefined} inert={!expanded && collapsedHeight === 0}
    data-collapsed={!expanded && collapsedHeight === 0 || undefined}
    ref={setRoot}>
    <div ref={inner} className="sliding-content__inner">{present ? children : null}</div>
  </div>;
}
