import {
  encodeLocalPathLink,
  resolveLocalFileReference,
  type LocalFileNameAvailability,
  type LocalFileNameIndex,
  type LocalFileReferenceContext,
} from "../../../entities/local-file/model/localFileReference";
import { getProjectContentFiles, type ProjectContentFileSnapshot } from "../../../services/project/getProjectContentFiles";
import { watchProjectFileEvents } from "../../../services/project/watchProjectFileEvents";

export function buildChatLocalFileNameIndex(
  snapshot: ProjectContentFileSnapshot,
  context: LocalFileReferenceContext,
): LocalFileNameIndex | null {
  if (!context.projectId || snapshot.project_id !== context.projectId || snapshot.unreadable_paths.length) return null;
  const index = new Map<string, Extract<ReturnType<typeof resolveLocalFileReference>, { lookup: "path" }>>();
  const duplicates = new Set<string>();
  for (const item of snapshot.items) {
    const name = item.name.toLowerCase();
    if (duplicates.has(name)) continue;
    if (index.has(name)) { index.delete(name); duplicates.add(name); continue; }
    const reference = resolveLocalFileReference(encodeLocalPathLink(`./${item.path}`), context);
    if (reference?.lookup === "path" && reference.scope === "workspace") index.set(name, reference);
  }
  return index;
}

/** One lazy index per chat project; filename links subscribe without rerendering
 * the message tree or starting a directory scan for each occurrence. */
export function createChatLocalFileNameAvailability(
  context: LocalFileReferenceContext,
  loadSnapshot = getProjectContentFiles,
  watchFiles = watchProjectFileEvents,
): LocalFileNameAvailability {
  let index: LocalFileNameIndex | null = null;
  const listeners = new Set<() => void>();
  let revision = 0;
  let request: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopWatching: (() => void) | null = null;
  let available = true;

  const publish = (next: LocalFileNameIndex | null) => {
    if (sameIndex(index, next)) return;
    index = next;
    for (const listener of listeners) listener();
  };
  const refresh = (expectedRevision: number) => {
    timer = null;
    if (!context.projectId || !listeners.size || !available) return;
    request?.abort();
    const controller = new AbortController();
    request = controller;
    void loadSnapshot(context.projectId, { signal: controller.signal }).then((snapshot) => {
      if (!controller.signal.aborted && expectedRevision === revision) {
        publish(buildChatLocalFileNameIndex(snapshot, context));
      }
    }, () => {
      if (!controller.signal.aborted && expectedRevision === revision) publish(null);
    });
  };
  const scheduleRefresh = () => {
    revision += 1;
    if (timer !== null) clearTimeout(timer);
    const expectedRevision = revision;
    timer = setTimeout(() => refresh(expectedRevision), 200);
  };

  return {
    getSnapshot: () => index,
    subscribe: (listener) => {
      listeners.add(listener);
      if (listeners.size === 1 && context.projectId && context.projectRootPath) {
        available = true;
        stopWatching = watchFiles(context.projectId, {
          onChanged: scheduleRefresh,
          onOverflow: scheduleRefresh,
          onStatusChanged: (nextAvailable) => {
            if (available === nextAvailable) return;
            available = nextAvailable;
            if (available) scheduleRefresh();
            else { revision += 1; request?.abort(); publish(null); }
          },
        });
        refresh(++revision);
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size) return;
        revision += 1;
        request?.abort();
        request = null;
        if (timer !== null) clearTimeout(timer);
        timer = null;
        stopWatching?.();
        stopWatching = null;
        index = null;
      };
    },
  };
}

function sameIndex(left: LocalFileNameIndex | null, right: LocalFileNameIndex | null) {
  if (left === right) return true;
  if (!left || !right || left.size !== right.size) return false;
  for (const [name, reference] of left) {
    if (right.get(name)?.absolutePath !== reference.absolutePath) return false;
  }
  return true;
}
