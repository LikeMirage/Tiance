export type AssetFileMetadata = {
  exists: boolean | null;
  mtimeMs: number | null;
};

export type AssetRefreshDecision =
  | { kind: "ignore" }
  | { kind: "mark-missing" }
  | { kind: "record-mtime"; mtimeMs: number }
  | { kind: "refresh"; mtimeMs: number | null };

export function decideAssetRefresh({
  currentMtimeMs,
  hasDetailedChange,
  metadata,
}: {
  currentMtimeMs: number | null;
  hasDetailedChange: boolean;
  metadata: AssetFileMetadata;
}): AssetRefreshDecision {
  if (metadata.exists === false) {
    return { kind: "mark-missing" };
  }

  if (hasDetailedChange) {
    return { kind: "refresh", mtimeMs: metadata.mtimeMs };
  }

  if (typeof metadata.mtimeMs !== "number") {
    return { kind: "ignore" };
  }

  if (typeof currentMtimeMs !== "number") {
    return { kind: "record-mtime", mtimeMs: metadata.mtimeMs };
  }

  return metadata.mtimeMs === currentMtimeMs
    ? { kind: "ignore" }
    : { kind: "refresh", mtimeMs: metadata.mtimeMs };
}
