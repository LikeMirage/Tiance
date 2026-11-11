/** Literal, case-insensitive matching; user text stays text (never HTML). */
export function KeywordHighlight({ text, keyword = "" }: { text: string; keyword?: string }) {
  const query = keyword.trim();
  if (!query) return <>{text}</>;
  const pattern = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  return <>{text.split(pattern).map((part, index) => index % 2
    ? <mark className="user-message-history__match" key={index}>{part}</mark>
    : part)}</>;
}
