import {
  encodeLocalPathLink,
  resolveLocalFileReference,
  type LocalFileNameAvailability,
  type LocalFileNameIndex,
  type LocalFileReferenceContext,
} from "../../../entities/local-file/model/localFileReference";
import { getProjectContentFiles, refreshProjectContentFiles, type ProjectContentFileSnapshot } from "../../../services/project/getProjectContentFiles";
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
  loadChanges = refreshProjectContentFiles,
): LocalFileNameAvailability {
  let index: LocalFileNameIndex | null = null;
  const files = new Map<string, ProjectContentFileSnapshot["items"][number]>();
  const unreadable = new Set<string>();
  const pending = new Set<string>();
  const listeners = new Set<() => void>();
  let full = true;
  let generation = 0;
  let request: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopWatching: (() => void) | null = null;
  let available = true;

  const publish = (next: LocalFileNameIndex | null) => {
    if (sameIndex(index, next)) return;
    index = next;
    for (const listener of listeners) listener();
  };
  const within = (path: string, scope: string) => !scope || scope === "." ||
    path.toLowerCase() === scope.toLowerCase() || path.toLowerCase().startsWith(scope.toLowerCase() + "/");
  const refresh = () => {
    timer = null;
    if (!context.projectId || !listeners.size || !available || request) return;
    if (!full && !pending.size) return;
    const isFull = full;
    const paths = [...pending];
    full = false;
    pending.clear();
    const expectedGeneration = generation;
    const controller = new AbortController();
    request = controller;
    const operation = isFull ? loadSnapshot(context.projectId, { signal: controller.signal })
      : loadChanges(context.projectId, paths, { signal: controller.signal });
    void operation.then((snapshot) => {
      if (controller.signal.aborted || generation !== expectedGeneration) return;
      if (snapshot.project_id !== context.projectId) throw new Error("Unexpected snapshot project");
      const replacements = new Map(snapshot.items.map(item => [item.path, item]));
      let changed = isFull;
      // Content-only modifications do not rebuild the filename map or messages.
      const existingPaths = !isFull && paths.every(path => files.has(path)) ? paths : files.keys();
      for (const path of existingPaths) {
        if ((isFull || paths.some(scope => within(path, scope))) && !replacements.has(path)) {
          files.delete(path); changed = true;
        }
      }
      for (const [path, item] of replacements) {
        if (!files.has(path)) changed = true;
        files.set(path, item);
      }
      for (const path of unreadable) {
        if (isFull || paths.some(scope => within(path, scope))) unreadable.delete(path);
      }
      for (const path of snapshot.unreadable_paths) unreadable.add(path);
      if (unreadable.size) publish(null);
      else if (changed || index === null) publish(buildChatLocalFileNameIndex({
        project_id: context.projectId!, items: [...files.values()], unreadable_paths: [],
      }, context));
    }).catch(() => {
      if (!controller.signal.aborted && generation === expectedGeneration) {
        publish(null); full = true;
      }
    }).finally(() => {
      if (request !== controller) return;
      request = null;
      // Changes during a scan become one trailing update, never a replacement
      // that cancels useful work. An error alone does not start a retry loop.
      if (pending.size && available && listeners.size) schedule();
    });
  };
  const schedule = () => {
    if (timer !== null || request) return;
    timer = setTimeout(refresh, 200);
  };
  const invalidateAll = () => { full = true; pending.add(""); schedule(); };

  return {
    getSnapshot: () => index,
    subscribe: (listener) => {
      listeners.add(listener);
      if (listeners.size === 1 && context.projectId && context.projectRootPath) {
        available = true;
        full = true;
        stopWatching = watchFiles(context.projectId, {
          onChanged: (paths) => { for (const path of paths) pending.add(path.replaceAll("\\", "/")); schedule(); },
          onOverflow: invalidateAll,
          onStatusChanged: (nextAvailable) => {
            if (available === nextAvailable) return;
            available = nextAvailable;
            if (available) invalidateAll();
            else { generation++; request?.abort(); publish(null); }
          },
        });
        refresh();
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size) return;
        generation++;
        request?.abort(); request = null;
        if (timer !== null) clearTimeout(timer);
        timer = null;
        stopWatching?.(); stopWatching = null;
        pending.clear(); files.clear(); unreadable.clear();
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
