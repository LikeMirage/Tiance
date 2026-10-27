import {
  checkSoftwareUpdate,
  checkSoftwareUpdateOnStartup,
  downloadSoftwareUpdate,
  installSoftwareUpdate,
  type SoftwareUpdateCheck,
  type SoftwareUpdateDownload,
} from "../../../services/system/softwareUpdate";

type Snapshot = {
  update: SoftwareUpdateCheck | null;
  download: SoftwareUpdateDownload | null;
  state: "idle" | "checking" | "downloading" | "ready" | "installing";
  prompt: "offer" | "restart" | null;
  error: string | null;
};

const services = {
  check: checkSoftwareUpdate,
  checkOnStartup: checkSoftwareUpdateOnStartup,
  download: downloadSoftwareUpdate,
  install: installSoftwareUpdate,
};

// App-owned state survives closing a prompt or navigating away from Settings.
export function createSoftwareUpdateStore(api = services) {
  let snapshot: Snapshot = {
    update: null, download: null, state: "idle", prompt: null, error: null,
  };
  const listeners = new Set<() => void>();
  let startupChecked = false;
  const publish = (patch: Partial<Snapshot>) => {
    snapshot = { ...snapshot, ...patch };
    listeners.forEach((listener) => listener());
  };
  const check = async (startup = false) => {
    if (startup && startupChecked) return;
    if (snapshot.state !== "idle") return;
    if (startup) startupChecked = true;
    publish({ state: "checking", error: null });
    try {
      const update = await (startup ? api.checkOnStartup() : api.check());
      publish({
        update,
        state: "idle",
        prompt: startup && update.updateAvailable && !update.sourceCheckout ? "offer" : null,
      });
    } catch (error) {
      publish({ state: "idle", error: toErrorMessage(error) });
    }
  };
  const install = async () => {
    if (snapshot.state === "ready") {
      publish({ prompt: "restart" });
      return;
    }
    if (snapshot.state !== "idle" || !snapshot.update?.updateAvailable || snapshot.update.sourceCheckout) return;
    publish({ state: "downloading", error: null });
    try {
      const download = await api.download();
      // Download completion only asks permission; installation requires a separate click.
      publish({ download, state: "ready", prompt: "restart" });
    } catch (error) {
      publish({ state: "idle", error: toErrorMessage(error), prompt: "offer" });
    }
  };
  const restart = async () => {
    if (snapshot.state !== "ready" || !snapshot.download) return;
    publish({ state: "installing", error: null });
    try {
      await api.install(snapshot.download);
    } catch (error) {
      // Keep the validated download for a retry without downloading again.
      publish({ state: "ready", error: toErrorMessage(error), prompt: "restart" });
    }
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    check: () => check(),
    checkOnStartup: () => check(true),
    install,
    restart,
    dismiss: () => publish({ prompt: null }),
  };
}

export const softwareUpdateStore = createSoftwareUpdateStore();

function toErrorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : "软件更新操作失败。";
}
