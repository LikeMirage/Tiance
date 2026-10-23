import { env } from "../../shared/config/env";
import { notifyGatewayAuthenticationRequired } from "./gatewayAuthenticationEvents";

export type GatewaySessionKind = "none" | "browser" | "desktop";

const heartbeatMs = 30_000;
let pageId = makePageId();
let pageHidden = false;
let enabled = false;
let timer: ReturnType<typeof setInterval> | null = null;
let pending: AbortController | null = null;
let activityVersion = 0;
let reportedActivityVersion = 0;
let lastSentAt = 0;

export async function configureGatewaySession(kind: GatewaySessionKind): Promise<void> {
  if (kind !== "browser") {
    stopGatewaySession();
    return;
  }
  if (!enabled) {
    enabled = true;
    activityVersion = reportedActivityVersion = 0;
    for (const event of ["pointerdown", "keydown", "wheel", "touchstart"]) {
      window.addEventListener(event, onActivity, { capture: true, passive: true });
    }
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    timer = setInterval(() => void pulse(), heartbeatMs);
  }
  await pulse();
}

export function stopGatewaySession(): void {
  enabled = false;
  if (timer !== null) clearInterval(timer);
  timer = null;
  pending?.abort();
  pending = null;
  for (const event of ["pointerdown", "keydown", "wheel", "touchstart"]) {
    window.removeEventListener(event, onActivity, true);
  }
  window.removeEventListener("pagehide", onPageHide);
  window.removeEventListener("pageshow", onPageShow);
}

function onActivity(event: Event): void {
  if (!event.isTrusted) return;
  activityVersion += 1;
  if (Date.now() - lastSentAt >= heartbeatMs) void pulse();
}

async function pulse(): Promise<void> {
  if (!enabled || pending !== null) return;
  const controller = new AbortController();
  pending = controller;
  lastSentAt = Date.now();
  const version = activityVersion;
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(`${env.apiBaseUrl}/gateway/security/session`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId, activity: version > reportedActivityVersion }),
      signal: controller.signal,
    });
    if (controller.signal.aborted || !enabled) return;
    if (response.status === 401) {
      stopGatewaySession();
      notifyGatewayAuthenticationRequired();
    } else if (response.ok) {
      reportedActivityVersion = version;
    }
  } catch {
    // A transport failure does not log out locally; the gateway owns expiry.
  } finally {
    clearTimeout(timeout);
    if (pending === controller) pending = null;
  }
}

function onPageHide(): void {
  if (!enabled) return;
  pageHidden = true;
  if (timer !== null) clearInterval(timer);
  timer = null;
  pending?.abort();
  pending = null;
  const url = `${env.apiBaseUrl}/gateway/security/session/leave`;
  const body = new Blob([JSON.stringify({ pageId })], { type: "application/json" });
  try {
    if (navigator.sendBeacon(url, body)) return;
  } catch { /* Fall through to a bounded keepalive request. */ }
  void fetch(url, { method: "POST", body, credentials: "include", keepalive: true }).catch(() => {});
}

function onPageShow(): void {
  if (!enabled) return;
  if (pageHidden) { pageId = makePageId(); pageHidden = false; }
  if (timer === null) timer = setInterval(() => void pulse(), heartbeatMs);
  void pulse();
}

function makePageId(): string {
  // crypto.randomUUID requires a secure context; LAN HTTP still needs lifecycle tracking.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
}
