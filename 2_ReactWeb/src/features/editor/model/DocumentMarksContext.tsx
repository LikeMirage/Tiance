import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { fetchJson } from "../../../services/http/httpClient";
import type { DocumentMark } from "./documentMarks";

type Changes = { add?: DocumentMark[]; remove?: string[] };
type MarkState = { marks: DocumentMark[]; saved: boolean; change: (changes: Changes) => Promise<boolean> };
const Context = createContext<MarkState | null>(null);
export const useDocumentMarks = () => useContext(Context);

export function DocumentMarksProvider({ tab, children }: { tab: DocumentTab | null; children: ReactNode }) {
  const path = tab?.projectFilePath;
  if (tab?.kind !== "text" || !tab.projectId || !path || tab.isMissing || !tab.textContentLoaded
    || tab.conversationDataView) return <>{children}</>;
  const endpoint = "/api/projects/" + encodeURIComponent(tab.projectId) + "/document-marks?path=" + encodeURIComponent(path);
  return <MarkSession key={endpoint} endpoint={endpoint} saved={!tab.isDirty && tab.content === tab.savedContent}>
    {children}
  </MarkSession>;
}

function MarkSession({ endpoint, saved, children }: { endpoint: string; saved: boolean; children: ReactNode }) {
  const [marks, setMarks] = useState<DocumentMark[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void fetchJson<DocumentMark[]>(endpoint, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setMarks(data); setError(""); }
    }).catch(() => { if (!controller.signal.aborted) setError("读取勾选失败"); });
    return () => controller.abort();
  }, [endpoint, attempt]);
  const change = useCallback(async ({ add = [], remove = [] }: Changes) => {
    try {
      await fetchJson(endpoint, { method: "PATCH", body: JSON.stringify({ add, remove }) });
      setMarks(current => {
        const items = new Map((current ?? []).map(mark => [mark.id, mark]));
        for (const mark of add) items.set(mark.id, mark);
        for (const id of remove) items.delete(id);
        return [...items.values()];
      });
      setError("");
      return true;
    } catch { setError("保存勾选失败，请重试"); return false; }
  }, [endpoint]);
  const state = useMemo(() => marks && ({ marks, saved, change }), [marks, saved, change]);
  return <Context.Provider value={state}>
    {children}
    {error && <div className="document-mark-error" role="alert">{error} <button type="button" onClick={() => {
      setError(""); retry(n => n + 1);
    }}>重新读取</button></div>}
  </Context.Provider>;
}
