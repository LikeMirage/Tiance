import { useEffect, useState } from "react";

import { getServerHealth, type ServerHealth } from "../../../services/system/getServerHealth";

type LoadState = "loading" | "ready" | "error";

interface UseServerHealthResult {
  state: LoadState;
  health: ServerHealth | null;
  error: string | null;
  reload: () => void;
}

export function useServerHealth(): UseServerHealthResult {
  const [health, setHealth] = useState<ServerHealth | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setState("loading");
      setError(null);

      try {
        const nextHealth = await getServerHealth();

        if (cancelled) {
          return;
        }

        setHealth(nextHealth);
        setState("ready");
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        const message =
          loadError instanceof Error ? loadError.message : "Unknown request failure.";
        setError(message);
        setState("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  return {
    state,
    health,
    error,
    reload: () => setRequestKey((current) => current + 1),
  };
}
