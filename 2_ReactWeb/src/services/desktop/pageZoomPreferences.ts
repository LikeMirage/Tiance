import { fetchJson } from "../http/httpClient";

type DesktopPageZoomPreferencesResponse = {
  version: number;
  zoom_factor: number | null;
};

type DesktopPageZoomPreferencesSaveRequest = {
  zoom_factor: number;
};

export async function getDesktopPageZoomPreference(): Promise<number | null> {
  const response = await fetchJson<DesktopPageZoomPreferencesResponse>(
    "/api/desktop/page-zoom-preferences",
  );
  return typeof response.zoom_factor === "number" ? response.zoom_factor : null;
}

export async function saveDesktopPageZoomPreference(zoomFactor: number): Promise<number | null> {
  const payload: DesktopPageZoomPreferencesSaveRequest = {
    zoom_factor: zoomFactor,
  };
  const response = await fetchJson<DesktopPageZoomPreferencesResponse>(
    "/api/desktop/page-zoom-preferences",
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
  return typeof response.zoom_factor === "number" ? response.zoom_factor : null;
}
