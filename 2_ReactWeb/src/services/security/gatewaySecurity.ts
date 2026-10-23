import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";
import { notifyGatewayAuthenticationRequired } from "./gatewayAuthenticationEvents";
import { configureGatewaySession, type GatewaySessionKind } from "./gatewaySessionLifecycle";

export type GatewaySecurityStatus = {
  password_configured: boolean;
  local_bypass_enabled: boolean;
  local_bypass_active: boolean;
  authenticated: boolean;
  session_kind: GatewaySessionKind;
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

export async function updateGatewayPassword(currentPassword: string | null, newPassword: string) {
  const result = await fetchJson<{ password_configured: true }>("/gateway/security/password", {
    body: JSON.stringify({ currentPassword, newPassword }),
    method: "PUT",
  });
  await configureGatewaySession((await getGatewaySecurityStatus()).session_kind);
  return result;
}

export async function removeGatewayPassword(currentPassword: string) {
  const result = await fetchJson<{ password_configured: false }>("/gateway/security/password", {
    body: JSON.stringify({ currentPassword }),
    method: "DELETE",
  });
  await configureGatewaySession("none");
  return result;
}

export async function saveGatewaySecuritySettings(settings: {
  localBypassEnabled: boolean;
  httpsEnabled: boolean;
  httpsPort: number;
  certificatePath: string;
  certificatePassword: string | null;
}) {
  const result = await fetchJson<{ restart_required: boolean }>("/gateway/security/settings", {
    body: JSON.stringify(settings),
    method: "PUT",
  });
  const status = await getGatewaySecurityStatus();
  await configureGatewaySession(status.session_kind);
  if (!status.authenticated) notifyGatewayAuthenticationRequired();
  return result;
}

export async function revokeGatewaySessions() {
  const result = await fetchJson<{ revoked: true }>("/gateway/security/sessions/revoke", { method: "POST" });
  notifyGatewayAuthenticationRequired();
  return result;
}

export function gatewaySecurityStatusUrl() {
  return `${env.apiBaseUrl}/gateway/security/status`;
}
