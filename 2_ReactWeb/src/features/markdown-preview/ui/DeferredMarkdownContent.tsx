import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import type { Components } from "react-markdown";
import { useContentLoadingTask } from "../../../shared/lib/contentReadiness";
import { getCachedMarkdownRender, requestMarkdownRender } from "../model/markdownRenderClient";
import { MARKDOWN_BLOCK_PREFIX, type MarkdownRenderDocument } from "../model/markdownRenderDocument";
import { scheduleMarkdownMount } from "../model/markdownMountQueue";
import { getMarkdownDomBlock, rememberMarkdownDomBlock } from "../model/markdownDomCache";

type Props = { content: string; components: Components; className: string };
type Result = { content: string; document?: MarkdownRenderDocument; error?: string };

export function DeferredMarkdownContent({ content, components, className }: Props) {
  const [result, setResult] = useState<Result | null>(() => ({ content, document: getCachedMarkdownRender(content) }));
  const [attempt, setAttempt] = useState(0);
  const cached = getCachedMarkdownRender(content);
  const current = result?.content === content ? result : null;
  const document = current?.document ?? cached;
  useContentLoadingTask(!document && !current?.error);
  useEffect(() => {
    if (getCachedMarkdownRender(content)) return;
    let disposed = false;
    const request = requestMarkdownRender(content);
    void request.promise.then((document) => {
      if (!disposed) setResult({ content, document });
    }, (error) => {
      if (!disposed) setResult({ content, error: error instanceof Error ? error.message : "内容加载失败" });
    });
    return () => { disposed = true; request.cancel(); };
  }, [content, attempt]);

  if (document) return <RenderedMarkdownDocument key={content} document={document} components={components} className={className} />;
  return <div className={className} aria-busy={!current?.error}>
    {current?.error ? <div role="alert" className="markdown-preview__load-error">
      <span>{current.error}</span>
      <button type="button" onClick={() => { setResult(null); setAttempt((value) => value + 1); }}>重试</button>
    </div> : null}
  </div>;
}

function RenderedMarkdownDocument({ document, components, className }: Omit<Props, "content"> & { document: MarkdownRenderDocument }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [targets, setTargets] = useState<Element[]>([]);
  const [mounted, setMounted] = useState(false);
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let remaining = document.blocks.length;
    let disposed = false;
    const cancellations: (() => void)[] = [];
    const finish = () => {
      if (disposed) return;
      setTargets(Array.from(root.querySelectorAll("[data-markdown-slot]")));
      setMounted(true);
    };
    const discover = (parent: Node) => {
      const walker = window.document.createTreeWalker(parent, NodeFilter.SHOW_COMMENT);
      while (walker.nextNode()) {
        const anchor = walker.currentNode as Comment;
        if (!anchor.data.startsWith(MARKDOWN_BLOCK_PREFIX)) continue;
        const id = Number(anchor.data.slice(MARKDOWN_BLOCK_PREFIX.length));
        cancellations.push(scheduleMarkdownMount(() => {
          if (disposed) return;
          const range = window.document.createRange();
          range.selectNode(anchor);
          const cachedBlock = getMarkdownDomBlock(document, id);
          const fragment = cachedBlock
            ? cachedBlock.cloneNode(true) as DocumentFragment
            : range.createContextualFragment(document.blocks[id]);
          if (!cachedBlock) rememberMarkdownDomBlock(document, id, fragment);
          discover(fragment);
          anchor.replaceWith(fragment);
          remaining -= 1;
          if (!remaining) finish();
        }));
      }
    };
    discover(root);
    if (!remaining) finish();
    return () => { disposed = true; cancellations.forEach((cancel) => cancel()); };
  }, [document]);
  useContentLoadingTask(!mounted || targets.length !== document.slots.length);
  const markup = useMemo(() => ({ __html: document.html }), [document]);
  const portals = useMemo(() => targets.map((target) => {
    const id = Number(target.getAttribute("data-markdown-slot"));
    const node = document.slots[id];
    return createPortal(toJsxRuntime({ type: "root", children: [node] }, {
      Fragment, jsx, jsxs, components, ignoreInvalidStyle: true, passKeys: true, passNode: true,
    }), target, String(id));
  }), [components, document, targets]);
  return <>
    <div ref={rootRef} className={className} aria-busy={!mounted} aria-hidden={!mounted || undefined} style={!mounted ? { opacity: 0 } : undefined} dangerouslySetInnerHTML={markup} />
    {portals}
  </>;
}
