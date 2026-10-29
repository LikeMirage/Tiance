import { getDesktopShellApi } from "./desktopShellStore";

export type DesktopCloseRequest = ReturnType<typeof observeDesktopCloseRequest>;

/** Only active during a user-requested close, never a background health poll. */
export function observeDesktopCloseRequest(requestId: string) {
  let state: "waiting" | "saving" = "waiting";
  let stopped = false;
  let reporting = false;
  let timer: ReturnType<typeof setInterval> | undefined;
  const stop = () => {
    stopped = true;
    clearInterval(timer);
  };
  const report = async () => {
    if (stopped || reporting) return;
    reporting = true;
    try {
      const accepted = await getDesktopShellApi()?.report_window_close?.(requestId, state);
      if (accepted === false) stop();
    } catch {
      // The shell watchdog, independent of this bridge, owns failure handling.
    } finally {
      reporting = false;
    }
  };
  timer = setInterval(() => { void report(); }, 1000);
  void report();
  return {
    requestId,
    setState(next: "waiting" | "saving") { state = next; void report(); },
    stop,
    cancel() {
      if (stopped) return;
      stop();
      void Promise.resolve(getDesktopShellApi()?.report_window_close?.(requestId, "cancelled"))
        .catch(() => undefined);
    },
  };
}

/** Browser-only windows have no native close request. */
export async function requestDesktopWindowClose(intent: "close" | "exit" = "close"): Promise<boolean> {
  const api = getDesktopShellApi();
  if (!api) return false;
  await api.request_window_close(intent);
  return true;
}
