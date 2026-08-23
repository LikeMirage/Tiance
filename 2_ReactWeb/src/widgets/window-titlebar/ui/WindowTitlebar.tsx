import "./window-titlebar.css";

import type { MouseEvent } from "react";
import { useI18n } from "@/shared/i18n";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import { useWindowTitlebarDrag } from "../model/useWindowTitlebarDrag";
import {
  CloseIcon,
  MaximizeIcon,
  MinimizeIcon,
  RestoreIcon,
} from "./windowTitlebarIcons";

type WindowTitlebarProps = {
  onRequestClose?: () => void;
};

export function WindowTitlebar({ onRequestClose }: WindowTitlebarProps) {
  const { t } = useI18n();
  const {
    state,
    minimize,
    toggleMaximize,
    close,
    getBounds,
    moveWindow,
    canStartNativeDrag,
    startNativeDrag,
    restoreForDrag,
  } = useDesktopShell();
  const nativeDragApiReady = typeof window.pywebview?.api?.start_window_drag === "function";
  const titlebarDrag = useWindowTitlebarDrag({
    canStartNativeDrag: canStartNativeDrag || nativeDragApiReady,
    getBounds,
    isAvailable: state.available || nativeDragApiReady,
    isFrameless: state.frameless || nativeDragApiReady,
    isMaximized: state.maximized,
    moveWindow,
    startNativeDrag,
    restoreForDrag,
  });

  return (
    <header className="window-titlebar">
      <div
        className="window-titlebar__drag"
        onDoubleClick={() => void toggleMaximize()}
        onPointerDown={titlebarDrag.handleDragPointerDown}
        onPointerMove={titlebarDrag.handleDragPointerMove}
        onPointerUp={titlebarDrag.handleDragPointerEnd}
        onPointerCancel={titlebarDrag.handleDragPointerEnd}
        onLostPointerCapture={titlebarDrag.clearActiveDrag}
      >
        <span className="window-titlebar__title">{t("common.productName")}</span>
      </div>

      <div className="window-titlebar__controls" aria-label={t("common.windowControls.group")}>
        <button
          className="window-titlebar__button window-titlebar__button--minimize"
          type="button"
          aria-label={t("common.windowControls.minimize")}
          onMouseDown={preventWindowControlMouseFocus}
          onClick={() => void minimize()}
          disabled={!state.available}
        >
          <MinimizeIcon />
        </button>
        <button
          className="window-titlebar__button window-titlebar__button--maximize"
          type="button"
          aria-label={
            state.maximized
              ? t("common.windowControls.restore")
              : t("common.windowControls.maximize")
          }
          onMouseDown={preventWindowControlMouseFocus}
          onClick={() => void toggleMaximize()}
          disabled={!state.available}
        >
          {state.maximized ? <RestoreIcon /> : <MaximizeIcon />}
        </button>
        <button
          className="window-titlebar__button window-titlebar__button--close"
          type="button"
          aria-label={t("common.windowControls.close")}
          onMouseDown={preventWindowControlMouseFocus}
          onClick={() => {
            if (onRequestClose) {
              onRequestClose();
              return;
            }
            void close();
          }}
          disabled={!state.available}
        >
          <CloseIcon />
        </button>
      </div>
    </header>
  );
}

function preventWindowControlMouseFocus(event: MouseEvent<HTMLButtonElement>) {
  event.preventDefault();
}
