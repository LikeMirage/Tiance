import { useCallback, useEffect, useLayoutEffect, useRef, type UIEvent } from "react";

import {
  functionalModelSettingsSections,
  type FunctionalModelSettingsSectionId,
} from "../model/functionalModelSections";
import { useI18n } from "../../../shared/i18n";
import { ConversationNamingModelSettings } from "./ConversationNamingModelSettings";
import { DefaultConversationRoleSettings } from "./DefaultConversationRoleSettings";
import { MemoryCompressionModelSettings } from "./MemoryCompressionModelSettings";
import {
  GlobalMemoryManagementModelSettings,
  ProjectMemoryManagementModelSettings,
} from "./MemoryManagementModelSettings";

import "./functional-model-settings.css";

const PROGRAMMATIC_SCROLL_DURATION_MS = 380;
const PROGRAMMATIC_SCROLL_EPSILON = 2;

type FunctionalModelSettingsPanelProps = {
  activeSectionId: FunctionalModelSettingsSectionId;
  onReady?: () => void;
  onSelectSection: (sectionId: FunctionalModelSettingsSectionId) => void;
};

export function FunctionalModelSettingsPanel({
  activeSectionId,
  onReady,
  onSelectSection,
}: FunctionalModelSettingsPanelProps) {
  const { t } = useI18n();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const sectionRefs = useRef(new Map<FunctionalModelSettingsSectionId, HTMLElement>());
  const activeSectionIdRef = useRef(activeSectionId);
  const isProgrammaticScrollRef = useRef(false);
  const isScrollSyncSelectionRef = useRef(false);
  const programmaticScrollTimerRef = useRef<number | null>(null);
  const programmaticScrollFrameRef = useRef<number | null>(null);

  const cancelProgrammaticScroll = useCallback(() => {
    if (programmaticScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(programmaticScrollFrameRef.current);
      programmaticScrollFrameRef.current = null;
    }

    if (programmaticScrollTimerRef.current !== null) {
      window.clearTimeout(programmaticScrollTimerRef.current);
      programmaticScrollTimerRef.current = null;
    }
  }, []);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const syncPageHeight = () => {
      viewport.style.setProperty(
        "--functional-model-page-height",
        `${viewport.clientHeight}px`,
      );
    };

    syncPageHeight();

    if (typeof ResizeObserver !== "undefined") {
      const resizeObserver = new ResizeObserver(syncPageHeight);
      resizeObserver.observe(viewport);
      return () => {
        resizeObserver.disconnect();
      };
    }

    window.addEventListener("resize", syncPageHeight);
    return () => {
      window.removeEventListener("resize", syncPageHeight);
    };
  }, []);

  useEffect(() => {
    activeSectionIdRef.current = activeSectionId;
    if (isScrollSyncSelectionRef.current) {
      isScrollSyncSelectionRef.current = false;
      return;
    }

    const section = sectionRefs.current.get(activeSectionId);
    const viewport = viewportRef.current;
    if (!section || !viewport) {
      return;
    }

    const targetTop = section.offsetTop;
    const startTop = viewport.scrollTop;
    cancelProgrammaticScroll();
    if (Math.abs(startTop - targetTop) <= PROGRAMMATIC_SCROLL_EPSILON) {
      isProgrammaticScrollRef.current = false;
      delete viewport.dataset.programmaticScroll;
      return;
    }

    isProgrammaticScrollRef.current = true;
    viewport.dataset.programmaticScroll = "true";

    const distance = targetTop - startTop;
    const startedAt = window.performance.now();

    const finishProgrammaticScroll = () => {
      cancelProgrammaticScroll();
      viewport.scrollTop = targetTop;
      isProgrammaticScrollRef.current = false;
      delete viewport.dataset.programmaticScroll;
    };

    const step = (now: number) => {
      const progress = Math.min(
        1,
        (now - startedAt) / PROGRAMMATIC_SCROLL_DURATION_MS,
      );
      viewport.scrollTop = startTop + distance * easeOutCubic(progress);

      if (progress < 1) {
        programmaticScrollFrameRef.current = window.requestAnimationFrame(step);
        return;
      }

      finishProgrammaticScroll();
    };

    programmaticScrollFrameRef.current = window.requestAnimationFrame(step);
    programmaticScrollTimerRef.current = window.setTimeout(() => {
      finishProgrammaticScroll();
    }, PROGRAMMATIC_SCROLL_DURATION_MS + 120);
  }, [activeSectionId, cancelProgrammaticScroll]);

  useEffect(() => () => {
    cancelProgrammaticScroll();
  }, [cancelProgrammaticScroll]);

  useEffect(() => {
    onReady?.();
  }, [onReady]);

  const handleScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (isProgrammaticScrollRef.current) {
      return;
    }

    const viewport = event.currentTarget;
    const nextSectionId = resolveNearestSectionId(viewport, sectionRefs.current);
    if (nextSectionId && nextSectionId !== activeSectionIdRef.current) {
      activeSectionIdRef.current = nextSectionId;
      isScrollSyncSelectionRef.current = true;
      onSelectSection(nextSectionId);
    }
  }, [onSelectSection]);

  return (
    <div
      ref={viewportRef}
      className="functional-model-settings__viewport"
      onScroll={handleScroll}
    >
      <div className="functional-model-settings__canvas">
        {functionalModelSettingsSections.map((section) => (
          <section
            key={section.id}
            ref={(node) => {
              if (node) {
                sectionRefs.current.set(section.id, node);
                return;
              }

              sectionRefs.current.delete(section.id);
            }}
            className="functional-model-settings__page"
            aria-label={t(section.labelKey)}
          >
            {renderFunctionalModelSection(section.id)}
          </section>
        ))}
      </div>
    </div>
  );
}

function renderFunctionalModelSection(sectionId: FunctionalModelSettingsSectionId) {
  switch (sectionId) {
    case "default-conversation":
      return (
        <div className="functional-model-settings">
          <DefaultConversationRoleSettings />
        </div>
      );
    case "conversation-naming":
      return (
        <div className="functional-model-settings">
          <ConversationNamingModelSettings />
        </div>
      );
    case "memory-compression":
      return (
        <div className="functional-model-settings">
          <MemoryCompressionModelSettings />
        </div>
      );
    case "project-memory-management":
      return (
        <div className="functional-model-settings">
          <ProjectMemoryManagementModelSettings />
        </div>
      );
    case "global-memory-management":
      return (
        <div className="functional-model-settings">
          <GlobalMemoryManagementModelSettings />
        </div>
      );
  }
}

function resolveNearestSectionId(
  viewport: HTMLDivElement,
  sectionRefs: Map<FunctionalModelSettingsSectionId, HTMLElement>,
) {
  const viewportFocusLine = viewport.scrollTop + viewport.clientHeight * 0.34;
  let nearestSectionId: FunctionalModelSettingsSectionId | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  sectionRefs.forEach((section, sectionId) => {
    const distance = Math.abs(section.offsetTop - viewportFocusLine);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestSectionId = sectionId;
    }
  });

  return nearestSectionId;
}

function easeOutCubic(progress: number) {
  return 1 - Math.pow(1 - progress, 3);
}
