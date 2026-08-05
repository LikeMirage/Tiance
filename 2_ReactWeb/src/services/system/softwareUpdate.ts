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

export const OPEN_SOURCE_REPOSITORY_URL = "https://github.com/LikeMirage/Tiance";
export const LATEST_SOFTWARE_DOWNLOAD_URL =
  "https://github.com/LikeMirage/Tiance/releases/latest/download/Tiance.zip";

export function checkSoftwareUpdate(signal?: AbortSignal) {
  return fetchJson<SoftwareUpdateCheck>("/api/software-update/check", { signal });
}

export function downloadSoftwareUpdate() {
  return fetchJson<SoftwareUpdateDownload>("/api/software-update/download", {
    method: "POST",
  });
}
