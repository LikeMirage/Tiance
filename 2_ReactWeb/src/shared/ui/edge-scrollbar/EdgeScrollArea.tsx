import { useId, useRef, type ComponentPropsWithoutRef, type RefObject } from "react";

import { useI18n } from "../../i18n";
import { EdgeScrollbar } from "./EdgeScrollbar";

type EdgeScrollAreaProps = ComponentPropsWithoutRef<"div"> & {
  frameClassName?: string;
  viewportRef?: RefObject<HTMLDivElement | null>;
  onUserScroll?: () => void;
};

/** Keeps the actual scrolling element available for focus, selection and reading position. */
export function EdgeScrollArea({
  frameClassName = "", viewportRef, onUserScroll, className = "", children, id, ...props
}: EdgeScrollAreaProps) {
  const { t } = useI18n();
  const localRef = useRef<HTMLDivElement>(null);
  const generatedId = useId();
  const scrollRef = viewportRef ?? localRef;
  const scrollId = id ?? generatedId;
  return (
    <div className={`edge-scroll-frame ${frameClassName}`}>
      <div {...props} className={`edge-scroll-viewport ${className}`} id={scrollId} ref={scrollRef}>
        {children}
      </div>
      <EdgeScrollbar scrollRef={scrollRef} scrollId={scrollId}
        label={props["aria-label"] ?? t("common.scrollbar")} onUserScroll={onUserScroll} />
    </div>
  );
}
