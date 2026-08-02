import { fetchJson } from "../http/httpClient";

export type NetworkConnectionMode = "system" | "direct" | "custom_proxy";
export type ProxyScheme = "http" | "https" | "socks5";
export type BackendPortMode = "auto" | "fixed";

export type NetworkSettings = {
  connection_mode: NetworkConnectionMode;
  proxy_scheme: ProxyScheme;
  proxy_host: string;
  proxy_port: number;
  connect_timeout_seconds: number;
  read_timeout_seconds: number;
  stream_timeout_seconds: number;
  backend_port_mode: BackendPortMode;
  fixed_backend_port: number;
};

export type NetworkSettingsResponse = {
  settings: NetworkSettings;
  default_settings: NetworkSettings;
  updated_at: string | null;
  backend_port_restart_required: boolean;
};

export type NetworkDiagnosticResponse = {
  ok: boolean;
  target: string;
  status_code: number | null;
  elapsed_ms: number;
  error: string | null;
};

export function getNetworkSettings() {
  return fetchJson<NetworkSettingsResponse>("/api/network/settings");
}

export function saveNetworkSettings(settings: NetworkSettings) {
  return fetchJson<NetworkSettingsResponse>("/api/network/settings", {
    body: JSON.stringify({ settings }),
    method: "PUT",
  });
}

export function diagnoseGithubConnection() {
  return fetchJson<NetworkDiagnosticResponse>("/api/network/diagnostics/github", {
    method: "POST",
  });
}
