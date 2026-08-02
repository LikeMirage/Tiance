import type { DesktopPathEntry } from "../../../shared/types/desktopShell";
import { isDesktopPathEntry } from "./desktopPathEntry";

const NATIVE_FILE_DROP_EVENT = "tiance-native-file-drop";

type TimerHandle = unknown;

export type DesktopFileDropEvent =
  | { kind: "resolved"; entries: DesktopPathEntry[] }
  | {
      kind: "unavailable";
      reason: "native_bridge_unavailable" | "native_path_timeout";
    };

export type NativeDesktopFileDrop = {
  dropId: string;
  targetId: string;
  entries: DesktopPathEntry[];
};

type DesktopFileDropCoordinatorOptions = {
  bufferLifetimeMs: number;
  onFileDrop: (event: DesktopFileDropEvent) => void;
  schedule?: (callback: () => void, delayMs: number) => TimerHandle;
  cancel?: (handle: TimerHandle) => void;
  targetId: string;
  waitTimeoutMs: number;
};

type BufferedDrop = {
  drop: NativeDesktopFileDrop;
  expiresHandle: TimerHandle;
};

export class DesktopFileDropCoordinator {
  private readonly bufferLifetimeMs: number;
  private readonly cancel: (handle: TimerHandle) => void;
  private readonly onFileDrop: (event: DesktopFileDropEvent) => void;
  private readonly schedule: (callback: () => void, delayMs: number) => TimerHandle;
  private readonly targetId: string;
  private readonly waitTimeoutMs: number;
  private bufferedDrop: BufferedDrop | null = null;
  private timeoutHandle: TimerHandle | null = null;
  private waitingDropId: string | null = null;

  constructor(options: DesktopFileDropCoordinatorOptions) {
    this.bufferLifetimeMs = options.bufferLifetimeMs;
    this.cancel = options.cancel ?? ((handle) => window.clearTimeout(handle as number));
    this.onFileDrop = options.onFileDrop;
    this.schedule = options.schedule ?? ((callback, delayMs) => window.setTimeout(callback, delayMs));
    this.targetId = options.targetId;
    this.waitTimeoutMs = options.waitTimeoutMs;
  }

  beginTargetDrop(dropId: string | null) {
    this.cancelWait();
    if (!dropId) {
      this.onFileDrop({ kind: "unavailable", reason: "native_bridge_unavailable" });
      return;
    }

    const bufferedDrop = this.takeBufferedDrop(dropId);
    if (bufferedDrop) {
      this.emitResolved(bufferedDrop);
      return;
    }

    this.waitingDropId = dropId;
    this.timeoutHandle = this.schedule(() => {
      if (this.waitingDropId !== dropId) return;
      this.waitingDropId = null;
      this.timeoutHandle = null;
      this.onFileDrop({ kind: "unavailable", reason: "native_path_timeout" });
    }, this.waitTimeoutMs);
  }

  receiveNativeDrop(drop: NativeDesktopFileDrop) {
    if (drop.targetId !== this.targetId) return;
    if (this.waitingDropId !== drop.dropId) {
      this.storeBufferedDrop(drop);
      return;
    }

    this.cancelWait();
    this.clearBufferedDrop();
    this.emitResolved(drop);
  }

  reset() {
    this.cancelWait();
    this.clearBufferedDrop();
  }

  private cancelWait() {
    this.waitingDropId = null;
    if (this.timeoutHandle === null) return;
    this.cancel(this.timeoutHandle);
    this.timeoutHandle = null;
  }

  private clearBufferedDrop() {
    if (!this.bufferedDrop) return;
    this.cancel(this.bufferedDrop.expiresHandle);
    this.bufferedDrop = null;
  }

  private emitResolved(drop: NativeDesktopFileDrop) {
    this.onFileDrop({ kind: "resolved", entries: drop.entries });
  }

  private storeBufferedDrop(drop: NativeDesktopFileDrop) {
    this.clearBufferedDrop();
    const expiresHandle = this.schedule(() => {
      if (this.bufferedDrop?.drop.dropId === drop.dropId) {
        this.bufferedDrop = null;
      }
    }, this.bufferLifetimeMs);
    this.bufferedDrop = { drop, expiresHandle };
  }

  private takeBufferedDrop(dropId: string) {
    const bufferedDrop = this.bufferedDrop;
    if (!bufferedDrop || bufferedDrop.drop.dropId !== dropId) return null;
    this.cancel(bufferedDrop.expiresHandle);
    this.bufferedDrop = null;
    return bufferedDrop.drop;
  }
}

export function subscribeNativeDesktopFileDrops(
  handler: (drop: NativeDesktopFileDrop) => void,
) {
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<unknown>).detail;
    if (!isNativeDesktopFileDrop(detail)) return;
    handler(detail);
  };
  window.addEventListener(NATIVE_FILE_DROP_EVENT, listener);
  return () => window.removeEventListener(NATIVE_FILE_DROP_EVENT, listener);
}

function isNativeDesktopFileDrop(value: unknown): value is NativeDesktopFileDrop {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const drop = value as Record<string, unknown>;
  return (
    typeof drop.dropId === "string" &&
    drop.dropId.trim().length > 0 &&
    typeof drop.targetId === "string" &&
    drop.targetId.trim().length > 0 &&
    Array.isArray(drop.entries) &&
    drop.entries.length > 0 &&
    drop.entries.every(isDesktopPathEntry)
  );
}
