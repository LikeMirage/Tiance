import { createContext, useContext, useLayoutEffect } from "react";

export function createContentReadiness() {
  let pending = 0;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  return {
    getSnapshot: () => pending,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    begin() {
      pending += 1;
      notify();
      let finished = false;
      return () => {
        if (finished) return;
        finished = true;
        pending -= 1;
        notify();
      };
    },
  };
}

export const ContentReadinessContext = createContext<ReturnType<typeof createContentReadiness> | null>(null);

export function useContentLoadingTask(pending: boolean) {
  const readiness = useContext(ContentReadinessContext);
  useLayoutEffect(() => pending ? readiness?.begin() : undefined, [pending, readiness]);
}
