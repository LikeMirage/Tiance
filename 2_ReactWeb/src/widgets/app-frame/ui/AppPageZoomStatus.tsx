import { MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useSyncExternalStore } from "react";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import { useI18n } from "../../../shared/i18n";
import { RangeSlider } from "../../../shared/ui/range-slider";
import {
  APP_PAGE_ZOOM_DEFAULT_FACTOR,
  APP_PAGE_ZOOM_MAX_FACTOR,
  APP_PAGE_ZOOM_MIN_FACTOR,
  APP_PAGE_ZOOM_STEP,
  getAppPageZoomSnapshot,
  setAppPageZoomFactor,
  subscribeAppPageZoom,
  syncAppPageZoomWithRuntime,
} from "../model/appPageZoom";

export function AppPageZoomStatus() {
  const { t } = useI18n();
  const { state } = useDesktopShell();
  const zoomSnapshot = useSyncExternalStore(
    subscribeAppPageZoom,
    getAppPageZoomSnapshot,
    getAppPageZoomSnapshot,
  );

  useEffect(() => {
    void syncAppPageZoomWithRuntime();
  }, [state.available]);

  const zoomPercent = useMemo(
    () => formatZoomPercent(zoomSnapshot.zoomFactor),
    [zoomSnapshot.zoomFactor],
  );
  const applyZoomFactor = (zoomFactor: number) => {
    void setAppPageZoomFactor(zoomFactor);
  };

  const handleZoomOut = () => {
    applyZoomFactor(zoomSnapshot.zoomFactor - APP_PAGE_ZOOM_STEP);
  };

  const handleZoomIn = () => {
    applyZoomFactor(zoomSnapshot.zoomFactor + APP_PAGE_ZOOM_STEP);
  };

  const handleReset = () => {
    applyZoomFactor(APP_PAGE_ZOOM_DEFAULT_FACTOR);
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) {
        return;
      }
      if (event.key !== "0") {
        return;
      }

      event.preventDefault();
      applyZoomFactor(APP_PAGE_ZOOM_DEFAULT_FACTOR);
    };

    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, []);

  return (
    <div className="app-page-zoom-status">
      <button
        type="button"
        className="app-page-zoom-status__trigger"
        aria-label={t("appFrame.zoom.status", { percent: zoomPercent })}
      >
        <MagnifyingGlass size={13} weight="bold" aria-hidden="true" />
        <span>{t("appFrame.zoom.status", { percent: zoomPercent })}</span>
      </button>
      <div className="app-page-zoom-popover" role="tooltip">
        <div className="app-page-zoom-popover__header">
          <span>{t("appFrame.zoom.panelTitle")}</span>
          <span>{zoomPercent}</span>
        </div>
        <div className="app-page-zoom-popover__controls">
          <button
            type="button"
            className="app-page-zoom-popover__button"
            onClick={handleZoomOut}
            aria-label={t("appFrame.zoom.decrease")}
          >
            -
          </button>
          <RangeSlider
            ariaLabel={t("appFrame.zoom.ratio")}
            ariaValueText={zoomPercent}
            className="app-page-zoom-popover__slider"
            max={APP_PAGE_ZOOM_MAX_FACTOR}
            min={APP_PAGE_ZOOM_MIN_FACTOR}
            step={APP_PAGE_ZOOM_STEP}
            value={zoomSnapshot.zoomFactor}
            onValueChange={applyZoomFactor}
          />
          <button
            type="button"
            className="app-page-zoom-popover__button"
            onClick={handleZoomIn}
            aria-label={t("appFrame.zoom.increase")}
          >
            +
          </button>
        </div>
        <div className="app-page-zoom-popover__footer">
          <span>{t(getZoomModeLabelKey(zoomSnapshot.mode))}</span>
          <button
            type="button"
            className="app-page-zoom-popover__reset"
            onClick={handleReset}
          >
            {t("common.actions.reset")}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatZoomPercent(zoomFactor: number) {
  return `${Math.round(zoomFactor * 100)}%`;
}

function getZoomModeLabelKey(mode: "native" | "unavailable") {
  if (mode === "native") {
    return "appFrame.zoom.native";
  }
  return "appFrame.zoom.waiting";
}
