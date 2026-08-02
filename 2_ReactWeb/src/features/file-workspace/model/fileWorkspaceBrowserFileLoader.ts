import type { FileWorkspaceTreeResponse } from "../../../entities/file-workspace/model/fileWorkspace";
import type {
  FileWorkspaceApi,
  FileWorkspaceListOptions,
} from "./fileWorkspaceApi";
import { isAbortError } from "../../../services/http/httpErrors";

const FILE_TREE_REQUEST_TIMEOUT_MS = 8000;

type FileWorkspaceLoadInit = {
  signal?: AbortSignal;
};

export async function getFileWorkspaceTreeWithTimeout(
  api: FileWorkspaceApi,
  options: FileWorkspaceListOptions = {},
  init: FileWorkspaceLoadInit = {},
): Promise<FileWorkspaceTreeResponse> {
  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = window.setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, FILE_TREE_REQUEST_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (init.signal?.aborted) {
    controller.abort();
  } else {
    init.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    return await api.listTree(options, {
      signal: controller.signal,
    });
  } catch (err) {
    if (isAbortError(err)) {
      if (didTimeout) {
        throw new Error("文件列表加载超时，请稍后重试。");
      }
      throw err;
    }
    throw err;
  } finally {
    window.clearTimeout(timeoutId);
    init.signal?.removeEventListener("abort", abortFromCaller);
  }
}
