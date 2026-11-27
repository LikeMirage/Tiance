import type { ProjectMemoryOperationInput } from "../../entities/project-memory/model/projectMemory";

type MemoryChange = Pick<ProjectMemoryOperationInput, "scope" | "operation">;
type Listener = (projectId: string | null, change: MemoryChange) => void;
const listeners = new Set<Listener>();

export function subscribeMemoryChanges(listener: Listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function notifyMemoryChanged(projectId: string | null, change: MemoryChange) {
  for (const listener of listeners) listener(projectId, change);
}
