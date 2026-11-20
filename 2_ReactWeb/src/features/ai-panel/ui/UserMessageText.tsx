import { Fragment } from "react";
import { KeywordHighlight } from "./KeywordHighlight";

export function UserMessageText({ text, keyword }: { text: string; keyword?: string }) {
  const nodes = [];
  let start = 0;
  for (const match of text.matchAll(/https?:\/\/[^\s<>"`，。；！？、（）【】《》“”]+/gi)) {
    let href = match[0].replace(/[.,;:!?]+$/, "");
    // Keep balanced parentheses in URLs such as Wikipedia article titles.
    while (href.endsWith(")") && href.split(")").length > href.split("(").length) href = href.slice(0, -1);
    if (!URL.canParse(href)) continue;
    nodes.push(<Fragment key={match.index}>
      <KeywordHighlight text={text.slice(start, match.index)} keyword={keyword} />
      <a href={href} target="_blank" rel="noreferrer"><KeywordHighlight text={href} keyword={keyword} /></a>
    </Fragment>);
    start = match.index + href.length;
  }
  return <>{nodes}<KeywordHighlight text={text.slice(start)} keyword={keyword} /></>;
}
