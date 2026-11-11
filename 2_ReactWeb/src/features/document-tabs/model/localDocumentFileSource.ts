import { documentDisplayPath } from "../../../entities/editor/model/documentFilePath";
import { HttpRequestError } from "../../../services/http/httpClient";
import { readLocalEditorMetadata, readLocalEditorText, saveLocalEditorText } from "../../../services/editor/localEditorFiles";
import type { DocumentFileSourceRuntime } from "./documentFileSources";

export function createLocalDocumentSource(root: string, ownerProjectId: string): DocumentFileSourceRuntime {
  const source = { kind: "local" as const, id: root, projectId: ownerProjectId,
    key: `local:${ownerProjectId}:${root}` };
  const absolute = (path: string) => documentDisplayPath(source, path);
  return {
    source,
    getApi: () => ({
      readTextFile: async (path, init) => ({ ...await readLocalEditorText(absolute(path), init), path }),
      saveTextFile: async (path, content, options) => ({
        ...await saveLocalEditorText(absolute(path), content, options), path,
      }),
    }),
    readMetadata: async (path) => {
      try {
        const result = await readLocalEditorMetadata(absolute(path));
        return { exists: true, mtimeMs: result.mtime_ms };
      } catch (error) {
        if (error instanceof HttpRequestError && error.status === 404) return { exists: false, mtimeMs: null };
        throw error;
      }
    },
    // Recheck open files on return to the app, without scanning or polling a disk.
    watchFileEvents: ({ onOverflow }) => {
      const refresh = () => onOverflow?.();
      window.addEventListener("focus", refresh);
      return () => window.removeEventListener("focus", refresh);
    },
  };
}
