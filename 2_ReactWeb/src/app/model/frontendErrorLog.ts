import type { ErrorInfo } from "react";

export const FRONTEND_ERROR_LOG_KEY = "tiance.frontend-errors";
const MAX_RECORDS = 5;
const MAX_TEXT_LENGTH = 16000;

export function recordFrontendError(error: Error, info: ErrorInfo): void {
  console.error("Workspace render failed.", error, info.componentStack);
  try {
    const storage = window.localStorage;
    let records: unknown = [];
    try {
      records = JSON.parse(storage.getItem(FRONTEND_ERROR_LOG_KEY) ?? "[]");
    } catch {
      // A damaged record must not prevent saving the next failure.
    }
    const previous = Array.isArray(records) ? records.slice(-(MAX_RECORDS - 1)) : [];
    storage.setItem(FRONTEND_ERROR_LOG_KEY, JSON.stringify([...previous, {
      time: new Date().toISOString(),
      message: String(error.message ?? error).slice(0, MAX_TEXT_LENGTH),
      stack: error.stack?.slice(0, MAX_TEXT_LENGTH) ?? "",
      componentStack: info.componentStack?.slice(0, MAX_TEXT_LENGTH) ?? "",
    }]));
  } catch {
    // Storage may be unavailable or full; the recovery screen must still work.
  }
}
