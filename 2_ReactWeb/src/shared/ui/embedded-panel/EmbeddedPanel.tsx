import { X } from "@phosphor-icons/react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";
import { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "./embedded-panel.css";

/** Render in a host's content slot, without viewport positioning or a floating card. */
export function EmbeddedPanel({ container, id, title, ariaLabel, headerContent, children,
  className = "", onClose, panelRef, onKeyDown }: {
  container: HTMLElement | null;
  id: string;
  title: ReactNode;
  ariaLabel: string;
  headerContent?: ReactNode;
  children: ReactNode;
  className?: string;
  onClose: () => void;
  panelRef?: RefObject<HTMLDivElement | null>;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
}) {
  const localRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    localRef.current?.focus({ preventScroll: true });
  }, [container]);
  if (!container) return null;
  return createPortal(<div ref={node => {
    localRef.current = node;
    if (panelRef) panelRef.current = node;
  }} id={id} role="dialog" aria-label={ariaLabel} tabIndex={-1}
    className={`embedded-panel ${className}`}
    onKeyDown={event => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      } else onKeyDown?.(event);
    }}>
    <header className="embedded-panel__head">
      <strong className="embedded-panel__title">{title}</strong>
      <div className="embedded-panel__header-content">{headerContent}</div>
      <button type="button" className="embedded-panel__close" aria-label={`关闭${ariaLabel}`}
        title="返回输入" onClick={onClose}><X size={15} aria-hidden="true" /></button>
    </header>
    <div className="embedded-panel__body">{children}</div>
  </div>, container);
}
