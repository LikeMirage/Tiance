export function isAbortError(err: unknown): boolean {
  return typeof err === "object"
    && err !== null
    && "name" in err
    && (err as { name?: unknown }).name === "AbortError";
}
