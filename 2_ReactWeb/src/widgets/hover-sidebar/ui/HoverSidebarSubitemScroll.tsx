import { useId, useRef, type ReactNode } from "react";

import { EdgeScrollbar } from "../../../shared/ui/edge-scrollbar";

export function HoverSidebarSubitemScroll({ children, isOpen, label, refreshKey }: {
  children: ReactNode;
  isOpen: boolean;
  label: string;
  refreshKey: string;
}) {
  const scrollId = useId();
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className={`hover-sidebar__subitems${isOpen ? " hover-sidebar__subitems--open" : ""}`}>
      <div
        id={scrollId}
        ref={scrollRef}
        className="hover-sidebar__subitems-viewport"
        aria-label={label}
      >
        <div className="hover-sidebar__subitems-content">{children}</div>
      </div>
      <EdgeScrollbar scrollRef={scrollRef} scrollId={scrollId} label={label}
        refreshKey={refreshKey} enabled={isOpen} side="left" />
    </div>
  );
}
