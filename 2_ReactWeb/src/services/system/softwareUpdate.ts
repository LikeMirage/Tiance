import { fetchJson } from "../http/httpClient";

export type SoftwareUpdateCheck = {
  currentVersion: string;
  latestVersion: string;
  updateAvailable: boolean;
  releaseName: string;
  releaseNotes: string;
  publishedAt: string | null;
  downloadSize: number | null;
  sourceCheckout: boolean;
};

export type SoftwareUpdateDownload = {
  version: string;
  stagePath: string;
  packageSize: number;
};

export type SoftwareUpdateInstallPhase = "downloading" | "installing";

export const OPEN_SOURCE_REPOSITORY_URL = "https://github.com/LikeMirage/Tiance";
export const LATEST_SOFTWARE_DOWNLOAD_URL =
  "https://github.com/LikeMirage/Tiance/releases/latest/download/Tiance.zip";

export function checkSoftwareUpdate(signal?: AbortSignal) {
  return fetchJson<SoftwareUpdateCheck>("/api/software-update/check", { signal });
}

let startupCheck: Promise<SoftwareUpdateCheck> | null = null;

export function checkSoftwareUpdateOnStartup() {
  startupCheck ??= checkSoftwareUpdate();
  return startupCheck;
}

export function downloadSoftwareUpdate() {
  return fetchJson<SoftwareUpdateDownload>("/api/software-update/download", {
    method: "POST",
  });
}

export async function installSoftwareUpdate(
  onPhase?: (phase: SoftwareUpdateInstallPhase) => void,
) {
  onPhase?.("downloading");
  const download = await downloadSoftwareUpdate();
  const installApi = window.pywebview?.api?.install_software_update;
  if (typeof installApi !== "function") {
    throw new Error("在线安装仅在天策桌面软件中可用。");
  }
  onPhase?.("installing");
  const result = await installApi(download.stagePath);
  if (!result.ok) throw new Error(result.error || "无法启动更新程序。");
  return result;
}
