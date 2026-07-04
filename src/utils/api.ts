const DEFAULT_DEPLOYED_API_BASE_URL = "https://fluxremote-mbyy.onrender.com";
const LOCAL_BACKEND_URL = "http://127.0.0.1:8000";

const normalizeServerUrl = (rawUrl: string) => {
  const normalized = rawUrl?.trim();
  if (!normalized) return DEFAULT_DEPLOYED_API_BASE_URL;

  try {
    const parsed = new URL(normalized);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.origin;
    }
    return normalized.replace(/\/+$/, "");
  } catch {
    return normalized.replace(/\/+$/, "");
  }
};

export const getApiBase = (overrideServerUrl?: string | null) => {
  if (overrideServerUrl?.trim()) {
    return normalizeServerUrl(overrideServerUrl);
  }

  const envUrl = import.meta.env.VITE_API_URL?.trim();
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    const port = window.location.port;
    if ((hostname === "localhost" || hostname === "127.0.0.1") && port === "5173") {
      // In local development, prefer the local backend unless a custom backend URL is explicitly configured.
      if (envUrl && envUrl !== DEFAULT_DEPLOYED_API_BASE_URL) {
        return normalizeServerUrl(envUrl);
      }
      return LOCAL_BACKEND_URL;
    }
  }

  if (envUrl) {
    return normalizeServerUrl(envUrl);
  }

  return DEFAULT_DEPLOYED_API_BASE_URL;
};

export { normalizeServerUrl };
