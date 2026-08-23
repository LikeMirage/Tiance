import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";

export type AnnouncementImportance = "normal" | "important" | "critical";
export type AnnouncementStatus = "published" | "withdrawn";

export type AnnouncementYearReference = {
  year: number;
  indexPath: string;
};

export type AnnouncementRootIndex = {
  schemaVersion: number;
  updatedAt: string;
  latestAnnouncementId: string;
  latestAnnouncementYear: number;
  years: AnnouncementYearReference[];
};

export type AnnouncementItem = {
  id: string;
  revision: number;
  title: string;
  summary: string;
  publishedAt: string;
  importance: AnnouncementImportance;
  status: AnnouncementStatus;
  contentPath: string;
  read: boolean;
};

export type AnnouncementYearIndex = {
  schemaVersion: number;
  year: number;
  updatedAt: string;
  announcements: AnnouncementItem[];
  cached: boolean;
};

export type AnnouncementSettings = {
  source: string;
  checkOnStartup: boolean;
};

export type AnnouncementCheck = {
  root: AnnouncementRootIndex;
  latestYear: AnnouncementYearIndex;
  latest: AnnouncementItem;
  latestUnread: boolean;
  cached: boolean;
  lastSuccessfulCheckAt: string | null;
};

export type AnnouncementContent = {
  announcement: AnnouncementItem;
  content: string;
  cached: boolean;
};

export function getAnnouncementSettings(signal?: AbortSignal) {
  return fetchJson<AnnouncementSettings>("/api/announcements/settings", { signal });
}

export function updateAnnouncementSettings(checkOnStartup: boolean) {
  return fetchJson<AnnouncementSettings>("/api/announcements/settings", {
    method: "PUT",
    body: JSON.stringify({ checkOnStartup }),
  });
}

let checkInFlight: Promise<AnnouncementCheck> | null = null;

export function checkAnnouncements() {
  checkInFlight ??= fetchJson<AnnouncementCheck>("/api/announcements/check", {
    method: "POST",
  }).finally(() => {
    checkInFlight = null;
  });
  return checkInFlight;
}

export function getAnnouncementYear(year: number, signal?: AbortSignal) {
  return fetchJson<AnnouncementYearIndex>(`/api/announcements/years/${year}`, { signal });
}

export function getAnnouncementContent(
  announcementId: string,
  revision: number,
  signal?: AbortSignal,
) {
  return fetchJson<AnnouncementContent>(
    `/api/announcements/${encodeURIComponent(announcementId)}/content?revision=${revision}`,
    { signal },
  );
}

export function markAnnouncementRead(announcementId: string, revision: number) {
  return fetchJson<{ announcementId: string; revision: number; readAt: string }>(
    `/api/announcements/${encodeURIComponent(announcementId)}/read`,
    { method: "POST", body: JSON.stringify({ revision }) },
  );
}

export function resolveAnnouncementAssetUrl(
  announcement: Pick<AnnouncementItem, "id" | "revision">,
  rawSource: string | undefined,
) {
  if (!rawSource) return "";
  const normalized = rawSource.replace(/\\/g, "/");
  if (
    !normalized.startsWith("assets/")
    || normalized.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    return "";
  }
  const path = normalized
    .slice("assets/".length)
    .split("/")
    .map(encodeURIComponent)
    .join("/");
  return `${env.apiBaseUrl}/api/announcements/${encodeURIComponent(announcement.id)}/assets/${path}?revision=${announcement.revision}`;
}
