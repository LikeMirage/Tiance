const defaultApiBaseUrl = "http://127.0.0.1:18000";
const frontendDevPorts = new Set(["18100"]);

type TianceBootWindow = Window & {
  __tianceApiBaseUrl?: string;
};

export const env = {
  apiBaseUrl: resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL),
};

function resolveApiBaseUrl(value: string | undefined) {
  if (typeof window !== "undefined") {
    const bootApiBaseUrl = readBootApiBaseUrl();
    if (bootApiBaseUrl) {
      return bootApiBaseUrl;
    }
  }

  if (value) {
    return stripTrailingSlash(value);
  }

  if (typeof window !== "undefined") {
    const { hostname, origin, port } = window.location;
    if ((hostname === "127.0.0.1" || hostname === "localhost") && frontendDevPorts.has(port)) {
      return defaultApiBaseUrl;
    }

    return stripTrailingSlash(origin);
  }

  return defaultApiBaseUrl;
}

function readBootApiBaseUrl() {
  if (typeof window === "undefined") {
    return null;
  }

  const bootWindow = window as TianceBootWindow;
  const value = bootWindow.__tianceApiBaseUrl ?? readBootApiBaseUrlFromHash();
  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);
    const isLocal =
      url.protocol === "http:" &&
      (url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "::1");
    return isLocal ? stripTrailingSlash(url.toString()) : null;
  } catch {
    return null;
  }
}

function readBootApiBaseUrlFromHash() {
  if (!window.location.hash) {
    return null;
  }

  const rawHash = window.location.hash.replace(/^#/, "");
  return new URLSearchParams(rawHash).get("tianceApiBaseUrl");
}

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}
