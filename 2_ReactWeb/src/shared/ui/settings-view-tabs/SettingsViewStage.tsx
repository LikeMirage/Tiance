import { useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";

import { SlidingViewStage } from "../sliding-view-stage/SlidingViewStage";

type SettingsViewStageProps<ViewId extends string> = {
  activeView: ViewId;
  children: ReactNode;
  className?: string;
  keepLeavingView?: boolean | ((leavingView: ViewId) => boolean);
  layout?: "content" | "fill";
  orderedViews: readonly ViewId[];
};

export function SettingsViewStage<ViewId extends string>({
  activeView,
  children,
  className,
  keepLeavingView = false,
  layout = "content",
  orderedViews,
}: SettingsViewStageProps<ViewId>) {
  const previousViewRef = useRef(activeView);
  const leavingView = previousViewRef.current;
  const direction = resolveViewDirection(orderedViews, leavingView, activeView);
  const shouldKeepLeavingView = typeof keepLeavingView === "function"
    ? keepLeavingView(leavingView)
    : keepLeavingView;

  useLayoutEffect(() => {
    previousViewRef.current = activeView;
  }, [activeView]);

  return (
    <SlidingViewStage
      className={className}
      direction={direction}
      keepLeavingView={shouldKeepLeavingView}
      layout={layout}
      viewKey={activeView}
    >
      {children}
    </SlidingViewStage>
  );
}

function resolveViewDirection<ViewId extends string>(
  orderedViews: readonly ViewId[],
  currentView: ViewId,
  nextView: ViewId,
) {
  const currentIndex = orderedViews.indexOf(currentView);
  const nextIndex = orderedViews.indexOf(nextView);
  if (currentIndex === -1 || nextIndex === -1 || nextIndex >= currentIndex) {
    return "forward" as const;
  }
  return "back" as const;
}
