import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";
import { notifyGatewayAuthenticationRequired } from "./gatewayAuthenticationEvents";

export type GatewaySecurityStatus = {
  password_configured: boolean;
  local_bypass_enabled: boolean;
  local_bypass_active: boolean;
  authenticated: boolean;
  https_enabled: boolean;
  https_port: number;
  certificate_path: string;
  restart_required: boolean;
};

export function getGatewaySecurityStatus() {
  return fetchJson<GatewaySecurityStatus>("/gateway/security/status");
}

export function loginGateway(password: string) {
  return fetchJson<{ authenticated: true }>("/gateway/security/login", {
    body: JSON.stringify({ password }),
    method: "POST",
  });
}

export async function logoutGateway() {
  const result = await fetchJson<{ authenticated: false }>("/gateway/security/logout", { method: "POST" });
  notifyGatewayAuthenticationRequired();
  return result;
}

export function updateGatewayPassword(currentPassword: string | null, newPassword: string) {
  return fetchJson<{ password_configured: true }>("/gateway/security/password", {
    body: JSON.stringify({ currentPassword, newPassword }),
    method: "PUT",
  });
}

export function removeGatewayPassword(currentPassword: string) {
  return fetchJson<{ password_configured: false }>("/gateway/security/password", {
    body: JSON.stringify({ currentPassword }),
    method: "DELETE",
  });
}

export function saveGatewaySecuritySettings(settings: {
  localBypassEnabled: boolean;
  httpsEnabled: boolean;
  httpsPort: number;
  certificatePath: string;
  certificatePassword: string | null;
}) {
  return fetchJson<{ restart_required: boolean }>("/gateway/security/settings", {
    body: JSON.stringify(settings),
    method: "PUT",
  });
}

export async function revokeGatewaySessions() {
  const result = await fetchJson<{ revoked: true }>("/gateway/security/sessions/revoke", { method: "POST" });
  notifyGatewayAuthenticationRequired();
  return result;
}

export function gatewaySecurityStatusUrl() {
  return `${env.apiBaseUrl}/gateway/security/status`;
}
