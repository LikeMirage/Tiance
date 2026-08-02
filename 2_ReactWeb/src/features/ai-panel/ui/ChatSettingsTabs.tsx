import { useEffect, useRef, type WheelEvent } from "react";
import { X } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import { useHorizontalScrollAnimation } from "../../../shared/model/horizontal-scroll-animation/useHorizontalScrollAnimation";
import type { ChatSettingsPanel } from "./ChatSettingsView";

type ChatSettingsTabsProps = {
  activePanel: ChatSettingsPanel;
  onClose: () => void;
  onSelectPanel: (panel: ChatSettingsPanel) => void;
};

export function ChatSettingsTabs({
  activePanel,
  onClose,
  onSelectPanel,
}: ChatSettingsTabsProps) {
  const { t } = useI18n();
  const activeTabRef = useRef<HTMLButtonElement | null>(null);
  const tabTrackRef = useRef<HTMLDivElement | null>(null);
  const {
    cancelHorizontalScroll,
    scrollHorizontallyTo,
  } = useHorizontalScrollAnimation();

  useEffect(() => {
    const tabTrack = tabTrackRef.current;
    const targetLeft = resolveSettingsTabScrollLeft(tabTrack, activeTabRef.current);
    if (tabTrack && targetLeft !== null) {
      scrollHorizontallyTo(tabTrack, targetLeft);
    }
  }, [activePanel, scrollHorizontallyTo]);

  useEffect(() => {
    const tabTrack = tabTrackRef.current;
    if (!tabTrack) return;

    const observer = new ResizeObserver(() => {
      const targetLeft = resolveSettingsTabScrollLeft(tabTrack, activeTabRef.current);
      if (targetLeft !== null) {
        scrollHorizontallyTo(tabTrack, targetLeft, { animate: false });
      }
    });
    observer.observe(tabTrack);
    return () => observer.disconnect();
  }, [scrollHorizontallyTo]);

  return (
    <nav className="ai-panel__tabs ai-panel__tabs--settings" aria-label={t("aiPanel.settingsTabs.aria")}>
      <div
        className="ai-panel__tab-track"
        data-active-panel={activePanel}
        ref={tabTrackRef}
        onWheel={(event) => {
          cancelHorizontalScroll();
          scrollSettingsTabsByWheel(event.currentTarget, event);
        }}
      >
        <span className="ai-panel__tab-indicator" aria-hidden="true" />
        <button
          className={
            activePanel === "basic"
              ? "ai-panel__tab ai-panel__tab--active"
              : "ai-panel__tab"
          }
          ref={activePanel === "basic" ? activeTabRef : undefined}
          type="button"
          onClick={() => onSelectPanel("basic")}
        >
          {t("aiPanel.settingsTabs.basic")}
        </button>
        <button
          className={
            activePanel === "memory"
              ? "ai-panel__tab ai-panel__tab--active"
              : "ai-panel__tab"
          }
          ref={activePanel === "memory" ? activeTabRef : undefined}
          type="button"
          onClick={() => onSelectPanel("memory")}
        >
          {t("aiPanel.settingsTabs.memory")}
        </button>
        <button
          className={
            activePanel === "globalMemory"
              ? "ai-panel__tab ai-panel__tab--active"
              : "ai-panel__tab"
          }
          ref={activePanel === "globalMemory" ? activeTabRef : undefined}
          type="button"
          onClick={() => onSelectPanel("globalMemory")}
        >
          {t("aiPanel.settingsTabs.globalMemory")}
        </button>
        <button
          className={
            activePanel === "tools"
              ? "ai-panel__tab ai-panel__tab--active"
              : "ai-panel__tab"
          }
          ref={activePanel === "tools" ? activeTabRef : undefined}
          type="button"
          onClick={() => onSelectPanel("tools")}
        >
          {t("aiPanel.settingsTabs.tools")}
        </button>
        <button
          className={
            activePanel === "data"
              ? "ai-panel__tab ai-panel__tab--active"
              : "ai-panel__tab"
          }
          ref={activePanel === "data" ? activeTabRef : undefined}
          type="button"
          onClick={() => onSelectPanel("data")}
        >
          {t("aiPanel.settingsTabs.data")}
        </button>
      </div>
      <button
        className="ai-panel__tab-close"
        type="button"
        aria-label={t("aiPanel.settingsTabs.close")}
        title={t("common.actions.close")}
        onClick={onClose}
      >
        <X size={14} weight="bold" aria-hidden="true" />
      </button>
    </nav>
  );
}

function scrollSettingsTabsByWheel(
  tabTrack: HTMLDivElement,
  event: WheelEvent<HTMLDivElement>,
) {
  const maxScrollLeft = tabTrack.scrollWidth - tabTrack.clientWidth;
  if (maxScrollLeft <= 0) {
    return;
  }

  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY)
    ? event.deltaX
    : event.deltaY;
  if (delta === 0) {
    return;
  }

  event.preventDefault();
  tabTrack.scrollLeft += delta;
}

function resolveSettingsTabScrollLeft(
  tabTrack: HTMLDivElement | null,
  activeTab: HTMLButtonElement | null,
) {
  if (!tabTrack || !activeTab) {
    return null;
  }

  const nextLeft = activeTab.offsetLeft -
    Math.max(0, (tabTrack.clientWidth - activeTab.offsetWidth) / 2);
  return Math.max(0, nextLeft);
}
