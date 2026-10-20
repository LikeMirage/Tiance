// Display budgets only. Never slice a document or save a partial projection.
export const previewPolicy = {
  richTextCharacters: 200_000,
  highlightedTextCharacters: 500_000,
  highlightedLineCharacters: 10_000,
} as const;

export function needsPlainTextMode(content: string) {
  if (content.length > previewPolicy.highlightedTextCharacters) return true;
  let lineLength = 0;
  for (let index = 0; index < content.length; index += 1) {
    lineLength = content.charCodeAt(index) === 10 ? 0 : lineLength + 1;
    if (lineLength > previewPolicy.highlightedLineCharacters) return true;
  }
  return false;
}
