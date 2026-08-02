import type { PropsWithChildren } from "react";

import "./app-frame.css";

import { AppStatusBarProvider, useAppStatusBar } from "../model/appStatusBar";
import { AppPageZoomStatus } from "./AppPageZoomStatus";
import { AppStatusBar } from "./AppStatusBar";
import { SystemMetricsStatus } from "./SystemMetricsStatus";
import { WindowResizeHandles } from "../../window-resize-handles/ui/WindowResizeHandles";

export function AppFrame({ children }: PropsWithChildren) {
  return (
    <AppStatusBarProvider>
      <AppFrameLayout>{children}</AppFrameLayout>
    </AppStatusBarProvider>
  );
}

function AppFrameLayout({ children }: PropsWithChildren) {
  const { statusBar } = useAppStatusBar();

  return (
    <main className="app-frame">
      <div className="app-frame__content">
        {children}
      </div>
      <AppStatusBar
        content={statusBar}
        systemRight={(
          <>
            <AppPageZoomStatus />
            <SystemMetricsStatus />
          </>
        )}
      />
      <WindowResizeHandles />
    </main>
  );
}
