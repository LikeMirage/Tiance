import { lazy, Suspense } from "react";

import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { useContentLoadingTask } from "../../../shared/lib/contentReadiness";
import type { MarkdownPreviewProps } from "./MarkdownPreview";

const MarkdownPreviewImpl = lazy(() =>
  import("./MarkdownPreview").then((module) => ({
    default: module.MarkdownPreview,
  })),
);

export function LazyMarkdownPreview(props: MarkdownPreviewProps) {
  return (
    <Suspense fallback={<MarkdownPreviewLoading isConversationContent={props.renderStrategy === "responsive"} />}>
      <MarkdownPreviewImpl {...props} />
    </Suspense>
  );
}

function MarkdownPreviewLoading({ isConversationContent }: { isConversationContent: boolean }) {
  useContentLoadingTask(isConversationContent);
  if (isConversationContent) return null;
  return (
    <LoadingStrip
      ariaLabel="正在加载 Markdown 预览"
      className="markdown-preview--loading"
      mode="fill"
      visual="ring"
    />
  );
}
