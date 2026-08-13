const AUTO_CHECK_STORAGE_KEY = "tiance.software-update.auto-check";

export function isAutomaticSoftwareUpdateCheckEnabled(): boolean {
  try {
    return window.localStorage.getItem(AUTO_CHECK_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function setAutomaticSoftwareUpdateCheckEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(AUTO_CHECK_STORAGE_KEY, String(enabled));
  } catch {
    // The preference remains enabled by default when browser storage is unavailable.
  }
}
