import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { LoadingStrip } from "./LoadingStrip";
import { LoadingBoundaryContext } from "./loadingBoundaryContext";

export function LoadingBoundary({ children, pending, actions }: {
  children: ReactNode;
  pending: boolean;
  actions?: ReactNode;
}) {
  const [revealed, setRevealed] = useState(false);
  const [tasks, setTasks] = useState(0);
  const activeTasks = useRef(0);
  const register = useCallback(() => {
    activeTasks.current += 1;
    setTasks(activeTasks.current);
    return () => {
      activeTasks.current -= 1;
      setTasks(activeTasks.current);
    };
  }, []);

  useLayoutEffect(() => {
    // Descendant layout effects register first, including Suspense hand-offs.
    if (!pending && activeTasks.current === 0) setRevealed(true);
  }, [pending, tasks]);

  return (
    <div className="ds-loading-boundary" aria-busy={!revealed || pending}>
      <LoadingBoundaryContext.Provider value={revealed ? null : register}>
        <div className="ds-loading-boundary__content" inert={!revealed} aria-hidden={!revealed}
          style={revealed ? undefined : { visibility: "hidden" }}>
          {children}
        </div>
      </LoadingBoundaryContext.Provider>
      {!revealed ? <div className="ds-loading-boundary__overlay">
        <LoadingStrip mode="fill" surface="dark" visual="ring" />
        {actions ? <div className="ds-loading-boundary__actions">{actions}</div> : null}
      </div> : null}
      {revealed && pending && actions ? <div className="ds-loading-boundary__actions">{actions}</div> : null}
    </div>
  );
}
