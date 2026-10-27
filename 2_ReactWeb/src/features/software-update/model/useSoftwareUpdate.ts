import { useEffect, useSyncExternalStore } from "react";
import { softwareUpdateStore } from "./softwareUpdateStore";

export function useSoftwareUpdate(checkOnMount = true) {
  const snapshot = useSyncExternalStore(softwareUpdateStore.subscribe, softwareUpdateStore.getSnapshot);
  useEffect(() => {
    if (checkOnMount && !softwareUpdateStore.getSnapshot().update) void softwareUpdateStore.check();
  }, [checkOnMount]);
  return { ...snapshot, ...softwareUpdateStore };
}
