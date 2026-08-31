import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { GatewayLoginPage, GatewayUnavailablePage } from "./features/access-security/ui/GatewayLoginPage";
import { subscribeGatewayAuthenticationRequired } from "./services/security/gatewayAuthenticationEvents";
import { getGatewaySecurityStatus } from "./services/security/gatewaySecurity";
import { getActiveThemeWithTimeout } from "./services/theme";
import { getWorkspaceLayoutPreferencesWithTimeout } from "./services/workspace/workspaceLayoutPreferences";
import type { WorkspaceLayoutPreferences } from "./entities/workspace/model/workspaceLayoutPreferences";
import {
  dismissFrontendBootPlaceholder,
  markFrontendStartup,
} from "./shared/model/startup-timing/startupTiming";
import { applyTheme, type ThemeDefinition } from "./shared/theme";
import "./shared/styles/globals.css";

markFrontendStartup("frontend: main module ready");

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element #root was not found.");
}

const root = ReactDOM.createRoot(rootElement);
markFrontendStartup("frontend: react root created");

let bootstrapRevision = 0;
let authenticationRefreshScheduled = false;

subscribeGatewayAuthenticationRequired(scheduleAuthenticationRefresh);
requestReactAppBootstrap();

function scheduleAuthenticationRefresh() {
  if (authenticationRefreshScheduled) return;
  authenticationRefreshScheduled = true;
  window.queueMicrotask(() => {
    authenticationRefreshScheduled = false;
    requestReactAppBootstrap();
  });
}

function requestReactAppBootstrap() {
  bootstrapRevision += 1;
  void bootstrapReactApp(root, bootstrapRevision);
}

async function bootstrapReactApp(root: ReactDOM.Root, revision: number) {
  let securityStatus;
  try {
    securityStatus = await getGatewaySecurityStatus();
  } catch (error) {
    if (revision !== bootstrapRevision) return;
    console.warn("Failed to read gateway security status.", error);
    dismissFrontendBootPlaceholder();
    root.render(
      <React.StrictMode>
        <GatewayUnavailablePage onRetry={requestReactAppBootstrap} />
      </React.StrictMode>,
    );
    return;
  }
  if (revision !== bootstrapRevision) return;
  if (!securityStatus.authenticated) {
    dismissFrontendBootPlaceholder();
    root.render(
      <React.StrictMode>
        <GatewayLoginPage onAuthenticated={requestReactAppBootstrap} />
      </React.StrictMode>,
    );
    return;
  }
  const [
    initialTheme,
    initialWorkspaceLayoutPreferences,
  ] = await Promise.all([
    loadStartupTheme(),
    loadStartupWorkspaceLayoutPreferences(),
  ]);

  if (revision !== bootstrapRevision) return;

  root.render(
    <React.StrictMode>
      <App
        initialTheme={initialTheme}
        initialWorkspaceLayoutPreferences={initialWorkspaceLayoutPreferences}
      />
    </React.StrictMode>,
  );
  markFrontendStartup("frontend: react render scheduled");
}

async function loadStartupTheme(): Promise<ThemeDefinition | null> {
  markFrontendStartup("frontend: startup theme load started");
  try {
    const theme = await getActiveThemeWithTimeout();
    applyTheme(theme);
    markFrontendStartup("frontend: startup theme applied");
    return theme;
  } catch (error) {
    console.warn("Failed to load startup theme before React render.", error);
    markFrontendStartup("frontend: startup theme load failed");
    return null;
  }
}

async function loadStartupWorkspaceLayoutPreferences(): Promise<WorkspaceLayoutPreferences | null> {
  markFrontendStartup("frontend: startup workspace layout load started");
  try {
    const preferences = await getWorkspaceLayoutPreferencesWithTimeout();
    markFrontendStartup("frontend: startup workspace layout loaded");
    return preferences;
  } catch (error) {
    console.warn("Failed to load workspace layout preferences before React render.", error);
    markFrontendStartup("frontend: startup workspace layout load failed");
    return null;
  }
}
