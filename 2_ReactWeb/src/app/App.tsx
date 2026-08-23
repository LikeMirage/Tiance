import { useCallback, useEffect } from "react";

import { I18nProvider } from "@/shared/i18n";

import { useAppTheme } from "./model/useAppTheme";
import { useBrowserShellGuards } from "./model/useBrowserShellGuards";
import { DesktopShellProvider } from "../features/desktop-shell/model/useDesktopShell";
import { StartupSoftwareUpdatePrompt } from "../features/software-update/ui/StartupSoftwareUpdatePrompt";
import { StartupAnnouncementPrompt } from "../features/announcements/ui/StartupAnnouncementPrompt";
import { revealDesktopShellWindow } from "../features/desktop-shell/model/desktopShellStore";
import { WorkspacePage } from "../pages/workspace/ui/WorkspacePage";
import { markFrontendStartup } from "../shared/model/startup-timing/startupTiming";
import { AppFrame } from "../widgets/app-frame/ui/AppFrame";
import type { WorkspaceLayoutPreferences } from "../entities/workspace/model/workspaceLayoutPreferences";
import type { ThemeDefinition } from "../shared/theme";

const DESKTOP_REVEAL_RETRY_DELAY_MS = 100;
const DESKTOP_REVEAL_RETRY_LIMIT = 80;

type AppProps = {
  initialWorkspaceLayoutPreferences: WorkspaceLayoutPreferences | null;
  initialTheme: ThemeDefinition | null;
};

export function App({
  initialTheme,
  initialWorkspaceLayoutPreferences,
}: AppProps) {
  useBrowserShellGuards();
  const themeControl = useAppTheme({
    initialTheme,
    loadOnMount: initialTheme === null,
  });

  useEffect(() => {
    markFrontendStartup("frontend: App mounted");
  }, []);

  const handleInitialWorkspaceSettled = useCallback(() => {
    window.requestAnimationFrame(() => {
      markFrontendStartup("frontend: workspace handoff first frame");
      window.requestAnimationFrame(() => {
        markFrontendStartup("frontend: App handoff frame");
        dismissFrontendBootPlaceholder();
      });
    });
  }, []);

  useEffect(() => {
    if (themeControl.isBootstrapping) {
      return;
    }

    let cancelled = false;
    let revealed = false;
    let retryCount = 0;
    let revealTimerId = 0;

    const removeReadyListeners = () => {
      window.removeEventListener("pywebviewready", requestReveal);
      document.removeEventListener("pywebviewready", requestReveal as EventListener);
    };

    const clearRevealTimer = () => {
      window.clearTimeout(revealTimerId);
      revealTimerId = 0;
    };

    const tryReveal = async () => {
      if (cancelled || revealed) {
        return;
      }

      try {
        const didReveal = await revealDesktopShellWindow();
        if (cancelled) {
          return;
        }

        if (!didReveal) {
          scheduleRevealRetry();
          return;
        }

        revealed = true;
        clearRevealTimer();
        removeReadyListeners();
        markFrontendStartup("frontend: desktop window reveal requested");
      } catch {
        scheduleRevealRetry();
      }
    };

    function scheduleRevealRetry() {
      if (cancelled || revealed || retryCount >= DESKTOP_REVEAL_RETRY_LIMIT) {
        return;
      }

      retryCount += 1;
      clearRevealTimer();
      revealTimerId = window.setTimeout(() => {
        void tryReveal();
      }, DESKTOP_REVEAL_RETRY_DELAY_MS);
    }

    function requestReveal() {
      void tryReveal();
    }

    window.addEventListener("pywebviewready", requestReveal);
    document.addEventListener("pywebviewready", requestReveal as EventListener);
    requestReveal();

    return () => {
      cancelled = true;
      removeReadyListeners();
      clearRevealTimer();
    };
  }, [themeControl.isBootstrapping]);

  return (
    <I18nProvider>
      <DesktopShellProvider>
        <AppFrame>
          <WorkspacePage
            initialLayoutPreferences={initialWorkspaceLayoutPreferences}
            onInitialWorkspaceSettled={handleInitialWorkspaceSettled}
            themeControl={themeControl}
          />
          <StartupAnnouncementPrompt />
          <StartupSoftwareUpdatePrompt />
        </AppFrame>
      </DesktopShellProvider>
    </I18nProvider>
  );
}

function dismissFrontendBootPlaceholder(): void {
  document.getElementById("tiance-boot-placeholder")?.remove();
}
