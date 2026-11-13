export type SpeechDraftOrigin = {
  projectId: string;
  sessionId: string;
  draft: string;
  caret: number | null;
};

export function insertSpeechText(current: string, origin: SpeechDraftOrigin, text: string): string {
  // Never apply an old offset to a draft edited while recognition was running.
  // In particular, a selected range is not replaced: speech is inserted after it.
  const offset = current === origin.draft && origin.caret !== null
    ? Math.max(0, Math.min(current.length, origin.caret)) : current.length;
  return current.slice(0, offset) + text + current.slice(offset);
}
