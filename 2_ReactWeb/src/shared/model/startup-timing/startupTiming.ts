type StartupMarkOptions = {
  force?: boolean;
  once?: boolean;
};

type StartupRequestTrace = {
  fail: (reason: unknown) => void;
  finish: (status: number) => void;
};

type PendingStartupMark = {
  browserElapsedMs: number;
  label: string;
};

const STARTUP_MARK_WINDOW_MS = 15_000;
const MAX_LABEL_LENGTH = 180;

const pendingMarks: PendingStartupMark[] = [];
const sentOnceLabels = new Set<string>();

let bridgeListenersBound = false;
let requestSequence = 0;

export function markFrontendStartup(
  label: string,
  options: StartupMarkOptions = {},
) {
  if (typeof window === "undefined") {
    return;
  }

  const browserElapsedMs = getBrowserElapsedMs();
  if (!options.force && browserElapsedMs > STARTUP_MARK_WINDOW_MS) {
    return;
  }

  const normalizedLabel = normalizeStartupLabel(label);
  if (options.once !== false) {
    if (sentOnceLabels.has(normalizedLabel)) {
      return;
    }
    sentOnceLabels.add(normalizedLabel);
  }

  pendingMarks.push({
    browserElapsedMs,
    label: normalizedLabel,
  });
  bindBridgeFlushEvents();
  flushStartupMarks();
}

export function createStartupRequestTrace(
  path: string,
  method = "GET",
): StartupRequestTrace | null {
  if (typeof window === "undefined") {
    return null;
  }

  const startedAt = getBrowserElapsedMs();
  if (startedAt > STARTUP_MARK_WINDOW_MS) {
    return null;
  }

  const requestId = ++requestSequence;
  const requestLabel = `api ${requestId}: ${method.toUpperCase()} ${normalizeStartupLabel(path)}`;

  markFrontendStartup(`${requestLabel} start`, { once: false });

  return {
    fail: (reason: unknown) => {
      markFrontendStartup(
        `${requestLabel} failed in ${formatDuration(getBrowserElapsedMs() - startedAt)}: ${formatFailureReason(reason)}`,
        { force: true, once: false },
      );
    },
    finish: (status: number) => {
      markFrontendStartup(
        `${requestLabel} done ${status} in ${formatDuration(getBrowserElapsedMs() - startedAt)}`,
        { force: true, once: false },
      );
    },
  };
}

function bindBridgeFlushEvents() {
  if (bridgeListenersBound) {
    return;
  }

  bridgeListenersBound = true;
  window.addEventListener("pywebviewready", flushStartupMarks);
  document.addEventListener("pywebviewready", flushStartupMarks as EventListener);
  window.addEventListener("focus", flushStartupMarks);
}

function flushStartupMarks() {
  if (pendingMarks.length === 0) {
    return;
  }

  const recordStartupMark = window.pywebview?.api?.record_startup_mark;
  if (typeof recordStartupMark !== "function") {
    return;
  }

  const marksToFlush = pendingMarks.splice(0, pendingMarks.length);
  marksToFlush.forEach((mark) => {
    try {
      void Promise.resolve(recordStartupMark(mark.label, mark.browserElapsedMs)).catch(
        () => undefined,
      );
    } catch {
      // 启动计时不能影响主流程。
    }
  });
}

function getBrowserElapsedMs() {
  return typeof performance !== "undefined" ? performance.now() : 0;
}

function normalizeStartupLabel(label: string) {
  const normalized = label.replace(/\s+/g, " ").trim();
  if (normalized.length <= MAX_LABEL_LENGTH) {
    return normalized;
  }

  return `${normalized.slice(0, MAX_LABEL_LENGTH - 1)}…`;
}

function formatDuration(durationMs: number) {
  return `${Math.max(0, durationMs).toFixed(1)}ms`;
}

function formatFailureReason(reason: unknown) {
  if (reason instanceof Error && reason.name) {
    return reason.name;
  }

  return "request error";
}
