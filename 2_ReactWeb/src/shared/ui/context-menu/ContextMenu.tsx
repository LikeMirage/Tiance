import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";

import { useDismissableLayer } from "../../model/dismissable-layer/useDismissableLayer";

import "./context-menu.css";

export type ContextMenuPosition = {
  x: number;
  y: number;
};

type ContextMenuProps = {
  children: ReactNode;
  className?: string;
  minWidth?: number;
  onClose: () => void;
  position: ContextMenuPosition;
};

type ContextMenuItemProps = {
  activation?: "click" | "press";
  children: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

type ContextMenuSubmenuProps = {
  children: ReactNode;
  disabled?: boolean;
  label: ReactNode;
};

type ContextMenuSeparatorProps = {
  className?: string;
};

const VIEWPORT_PADDING = 8;

export function ContextMenu({
  children,
  className,
  minWidth = 142,
  onClose,
  position,
}: ContextMenuProps) {
  const menuRef = useDismissableLayer<HTMLDivElement>({ onDismiss: onClose });
  const [resolvedPosition, setResolvedPosition] = useState(position);

  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node) {
      setResolvedPosition(position);
      return;
    }
    const rect = node.getBoundingClientRect();
    const maxLeft = Math.max(VIEWPORT_PADDING, window.innerWidth - rect.width - VIEWPORT_PADDING);
    const maxTop = Math.max(VIEWPORT_PADDING, window.innerHeight - rect.height - VIEWPORT_PADDING);
    setResolvedPosition({
      x: clamp(position.x, VIEWPORT_PADDING, maxLeft),
      y: clamp(position.y, VIEWPORT_PADDING, maxTop),
    });
  }, [children, menuRef, position]);

  const style: CSSProperties = {
    left: resolvedPosition.x,
    minWidth,
    top: resolvedPosition.y,
  };

  return createPortal(
    <>
      <div
        aria-hidden="true"
        className="ds-context-menu__dismiss-layer"
        onContextMenu={(event) => {
          event.preventDefault();
          onClose();
        }}
        onMouseDown={onClose}
        onPointerDown={onClose}
      />
      <div
        ref={menuRef}
        className={["ds-context-menu", className].filter(Boolean).join(" ")}
        role="menu"
        style={style}
      >
        {children}
      </div>
    </>,
    document.body,
  );
}

export function ContextMenuItem({
  activation = "press",
  children,
  danger = false,
  disabled = false,
  onSelect,
}: ContextMenuItemProps) {
  const pointerSelectRef = useRef(false);

  return (
    <button
      className={[
        "ds-context-menu__item",
        danger ? "ds-context-menu__item--danger" : "",
      ].filter(Boolean).join(" ")}
      disabled={disabled}
      role="menuitem"
      type="button"
      onMouseDown={(event) => {
        if (activation === "click") return;
        if (pointerSelectRef.current || disabled || event.button !== 0) return;
        pointerSelectRef.current = true;
        event.preventDefault();
        onSelect();
      }}
      onPointerDown={(event) => {
        if (activation === "click") return;
        if (disabled || event.button !== 0) return;
        pointerSelectRef.current = true;
        event.preventDefault();
        onSelect();
      }}
      onClick={() => {
        if (activation === "click") {
          if (!disabled) onSelect();
          return;
        }
        if (pointerSelectRef.current) {
          pointerSelectRef.current = false;
          return;
        }
        if (disabled) return;
        onSelect();
      }}
    >
      {children}
    </button>
  );
}

export function ContextMenuSubmenu({
  children,
  disabled = false,
  label,
}: ContextMenuSubmenuProps) {
  return (
    <div
      className="ds-context-menu__submenu-host"
      role="none"
    >
      <button
        aria-haspopup="menu"
        className="ds-context-menu__item ds-context-menu__submenu-trigger"
        disabled={disabled}
        role="menuitem"
        type="button"
      >
        {label}
      </button>
      {!disabled ? (
        <div
          className="ds-context-menu__submenu"
          role="menu"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function ContextMenuSeparator({ className }: ContextMenuSeparatorProps) {
  return (
    <div
      className={["ds-context-menu__separator", className].filter(Boolean).join(" ")}
      role="presentation"
    />
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
