import { useCallback, useEffect, useRef, useState } from "react";

import {
  checkSoftwareUpdate,
  installSoftwareUpdate,
  type SoftwareUpdateCheck,
} from "../../../services/system/softwareUpdate";

type OperationState = "idle" | "checking" | "downloading" | "installing";

export function useSoftwareUpdate() {
  const [update, setUpdate] = useState<SoftwareUpdateCheck | null>(null);
  const [state, setState] = useState<OperationState>("checking");
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const check = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setState("checking");
    setError(null);
    try {
      const result = await checkSoftwareUpdate();
      if (requestId === requestIdRef.current) setUpdate(result);
    } catch (requestError) {
      if (requestId === requestIdRef.current) {
        setError(toErrorMessage(requestError));
      }
    } finally {
      if (requestId === requestIdRef.current) setState("idle");
    }
  }, []);

  const install = useCallback(async () => {
    setState("downloading");
    setError(null);
    try {
      await installSoftwareUpdate((phase) => setState(phase));
    } catch (installError) {
      setError(toErrorMessage(installError));
      setState("idle");
    }
  }, []);

  useEffect(() => {
    void check();
    return () => {
      requestIdRef.current += 1;
    };
  }, [check]);

  return { check, error, install, state, update };
}

function toErrorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : "软件更新操作失败。";
}
