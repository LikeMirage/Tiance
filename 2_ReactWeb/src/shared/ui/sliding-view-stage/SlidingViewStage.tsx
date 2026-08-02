import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import "./sliding-view-stage.css";

export type SlidingViewStageDirection = "forward" | "back";

type SlidingViewStageTransition = {
  direction: SlidingViewStageDirection;
  id: number;
  leavingSnapshot: ReactNode;
} | null;

type SlidingViewStageProps = {
  children: ReactNode;
  className?: string;
  direction: SlidingViewStageDirection;
  durationMs?: number;
  keepLeavingView?: boolean;
  viewKey: string;
};

export function SlidingViewStage({
  children,
  className,
  direction,
  durationMs = 320,
  keepLeavingView = true,
  viewKey,
}: SlidingViewStageProps) {
  const previousViewKeyRef = useRef(viewKey);
  const latestChildrenRef = useRef(children);
  const transitionIdRef = useRef(0);
  const [transition, setTransition] = useState<SlidingViewStageTransition>(null);

  useLayoutEffect(() => {
    if (viewKey === previousViewKeyRef.current) {
      return;
    }

    const transitionId = transitionIdRef.current + 1;
    transitionIdRef.current = transitionId;
    setTransition({
      direction,
      id: transitionId,
      leavingSnapshot: latestChildrenRef.current,
    });
    previousViewKeyRef.current = viewKey;

    const timer = window.setTimeout(() => {
      setTransition((current) => current?.id === transitionId ? null : current);
    }, durationMs);
    return () => window.clearTimeout(timer);
  }, [direction, durationMs, viewKey]);

  useLayoutEffect(() => {
    latestChildrenRef.current = children;
  });

  const rootClassName = className
    ? `sliding-view-stage ${className}`
    : "sliding-view-stage";
  const currentClassName = transition
    ? transition.direction === "forward"
      ? "sliding-view-stage__view sliding-view-stage__view--static sliding-view-stage__view--enter-from-right"
      : "sliding-view-stage__view sliding-view-stage__view--static sliding-view-stage__view--enter-from-left"
    : "sliding-view-stage__view sliding-view-stage__view--static";
  const leavingClassName = transition?.direction === "forward"
    ? "sliding-view-stage__view sliding-view-stage__view--layer sliding-view-stage__view--exit-to-left"
    : "sliding-view-stage__view sliding-view-stage__view--layer sliding-view-stage__view--exit-to-right";

  return (
    <div
      className={rootClassName}
      style={{ "--sliding-view-stage-duration": `${durationMs}ms` } as CSSProperties}
    >
      <div className={currentClassName}>{children}</div>
      {transition && keepLeavingView ? (
        <div className={leavingClassName} aria-hidden="true">
          {transition.leavingSnapshot}
        </div>
      ) : null}
    </div>
  );
}
