import type { ProjectFileMutation } from "./project";

const PROJECT_FILE_MUTATION_EVENT = "project-file-mutation";

let mutationVersion = 0;
const mutationTarget = new EventTarget();

type ProjectFileMutationInput =
  | Omit<Extract<ProjectFileMutation, { action: "upsert" }>, "action" | "version"> & {
    action?: "upsert";
  }
  | Omit<Extract<ProjectFileMutation, { action: "move" }>, "version">
  | Omit<Extract<ProjectFileMutation, { action: "delete" }>, "version">;

export function publishProjectFileMutation(
  input: ProjectFileMutationInput,
): ProjectFileMutation {
  const version = mutationVersion + 1;
  const mutation: ProjectFileMutation = input.action === "delete"
    ? { ...input, version }
    : input.action === "move"
      ? { ...input, version }
    : { ...input, action: "upsert", version };
  mutationVersion = mutation.version;
  mutationTarget.dispatchEvent(new CustomEvent(PROJECT_FILE_MUTATION_EVENT, { detail: mutation }));
  return mutation;
}

export function subscribeProjectFileMutations(
  handler: (mutation: ProjectFileMutation) => void,
): () => void {
  const listener = (event: Event) => {
    handler((event as CustomEvent<ProjectFileMutation>).detail);
  };
  mutationTarget.addEventListener(PROJECT_FILE_MUTATION_EVENT, listener);
  return () => mutationTarget.removeEventListener(PROJECT_FILE_MUTATION_EVENT, listener);
}
