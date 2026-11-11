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
  withIcons?: boolean;
  onClose: () => void;
  position: ContextMenuPosition;
};

type ContextMenuItemProps = {
  activation?: "click" | "press";
  children: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  onSelect: () => void;
};

type ContextMenuSubmenuProps = {
  children: ReactNode;
  disabled?: boolean;
  icon?: ReactNode;
  label: ReactNode;
};

type ContextMenuSeparatorProps = {
  className?: string;
};

const VIEWPORT_PADDING = 8;
const SUBMENU_WIDTH = 180;

export function ContextMenu({
  children,
  className,
  minWidth = 142,
  withIcons = false,
  onClose,
  position,
}: ContextMenuProps) {
  const menuRef = useDismissableLayer<HTMLDivElement>({ onDismiss: onClose });
  const [resolvedPosition, setResolvedPosition] = useState(position);
  const [submenuLayout, setSubmenuLayout] = useState({ side: "right", width: SUBMENU_WIDTH });

  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node) {
      setResolvedPosition(position);
      return;
    }
    const updatePosition = () => {
      const rect = node.getBoundingClientRect();
      const maxLeft = Math.max(VIEWPORT_PADDING, window.innerWidth - rect.width - VIEWPORT_PADDING);
      const maxTop = Math.max(VIEWPORT_PADDING, window.innerHeight - rect.height - VIEWPORT_PADDING);
      const x = clamp(position.x, VIEWPORT_PADDING, maxLeft);
      const y = clamp(position.y, VIEWPORT_PADDING, maxTop);
      const rightSpace = Math.max(0, window.innerWidth - x - rect.width - VIEWPORT_PADDING);
      const leftSpace = Math.max(0, x - VIEWPORT_PADDING);
      const side = rightSpace >= SUBMENU_WIDTH || rightSpace >= leftSpace ? "right" : "left";
      const width = Math.min(SUBMENU_WIDTH, side === "right" ? rightSpace : leftSpace);
      setResolvedPosition((previous) => previous.x === x && previous.y === y ? previous : { x, y });
      setSubmenuLayout((previous) => previous.side === side && previous.width === width ? previous : { side, width });
    };
    updatePosition();
    const observer = new ResizeObserver(updatePosition);
    observer.observe(node);
    window.addEventListener("resize", updatePosition);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updatePosition);
    };
  }, [children, menuRef, position]);

  const style: CSSProperties & { "--context-submenu-width": string } = {
    left: resolvedPosition.x,
    minWidth,
    top: resolvedPosition.y,
    "--context-submenu-width": `${submenuLayout.width}px`,
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
        className={["ds-context-menu", withIcons ? "ds-context-menu--with-icons" : "", className].filter(Boolean).join(" ")}
        data-submenu-side={submenuLayout.side}
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
  icon,
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
      <span className="ds-context-menu__icon" aria-hidden="true">{icon}</span>
      <span className="ds-context-menu__label">{children}</span>
    </button>
  );
}

export function ContextMenuSubmenu({
  children,
  disabled = false,
  icon,
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
        <span className="ds-context-menu__icon" aria-hidden="true">{icon}</span>
        <span className="ds-context-menu__label">{label}</span>
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
