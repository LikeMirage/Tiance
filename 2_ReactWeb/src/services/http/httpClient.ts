import { env } from "../../shared/config/env";
import { createStartupRequestTrace } from "../../shared/model/startup-timing/startupTiming";

export class HttpRequestError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: unknown;

  constructor(message: string, status: number, code: string | null = null, details: unknown = null) {
    super(message);
    this.name = "HttpRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = buildRequestHeaders(init);
  const trace = createStartupRequestTrace(path, init?.method ?? "GET");

  let response: Response;
  try {
    response = await fetch(buildApiUrl(path), {
      ...init,
      headers,
    });
  } catch (requestError) {
    trace?.fail(requestError);
    throw requestError;
  }

  trace?.finish(response.status);

  if (!response.ok) {
    const error = await buildRequestError(response);
    throw new HttpRequestError(error.message, response.status, error.code, error.details);
  }

  return (await response.json()) as T;
}

export async function fetchNoContent(path: string, init?: RequestInit): Promise<void> {
  const headers = buildRequestHeaders(init);
  const trace = createStartupRequestTrace(path, init?.method ?? "GET");

  let response: Response;
  try {
    response = await fetch(buildApiUrl(path), {
      ...init,
      headers,
    });
  } catch (requestError) {
    trace?.fail(requestError);
    throw requestError;
  }

  trace?.finish(response.status);

  if (!response.ok) {
    const error = await buildRequestError(response);
    throw new HttpRequestError(error.message, response.status, error.code, error.details);
  }
}

function buildRequestHeaders(init?: RequestInit) {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return headers;
}

function buildApiUrl(path: string) {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${env.apiBaseUrl}${normalizedPath}`;
}

async function buildRequestError(response: Response): Promise<{
  code: string | null;
  details: unknown;
  message: string;
}> {
  const defaultMessage = `Request failed with status ${response.status}.`;
  const contentType = response.headers.get("Content-Type") ?? "";

  if (contentType.includes("application/json")) {
    try {
      const error = parseHttpErrorPayload(await response.json());
      if (error) return error;
    } catch {
      return { code: null, details: null, message: defaultMessage };
    }
  }

  try {
    const text = (await response.text()).trim();
    return { code: null, details: null, message: text.length > 0 ? text : defaultMessage };
  } catch {
    return { code: null, details: null, message: defaultMessage };
  }
}

export function parseHttpErrorPayload(payload: unknown): {
  code: string | null;
  details: unknown;
  message: string;
} | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const error = (payload as { error?: unknown }).error;
  if (!error || typeof error !== "object" || Array.isArray(error)) {
    return null;
  }
  const errorPayload = error as Record<string, unknown>;
  if (typeof errorPayload.message !== "string" || !errorPayload.message.trim()) {
    return null;
  }
  return {
    code: typeof errorPayload.code === "string" ? errorPayload.code : null,
    details: errorPayload.details ?? null,
    message: errorPayload.message,
  };
}
