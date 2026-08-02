import { lazy, Suspense } from "react";

import { LoadingStrip } from "../../../shared/ui/loading-strip";
import type { MarkdownPreviewProps } from "./MarkdownPreview";

const MarkdownPreviewImpl = lazy(() =>
  import("./MarkdownPreview").then((module) => ({
    default: module.MarkdownPreview,
  })),
);

export function LazyMarkdownPreview(props: MarkdownPreviewProps) {
  return (
    <Suspense fallback={<MarkdownPreviewLoading />}>
      <MarkdownPreviewImpl {...props} />
    </Suspense>
  );
}

function MarkdownPreviewLoading() {
  return (
    <LoadingStrip
      ariaLabel="正在加载 Markdown 预览"
      className="markdown-preview--loading"
      mode="fill"
      visual="ring"
    />
  );
}
