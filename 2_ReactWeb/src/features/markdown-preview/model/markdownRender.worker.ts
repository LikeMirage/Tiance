import { prepareMarkdownRender } from "./markdownRenderPipeline";

// Markdown parsing, sanitizing and KaTeX all run outside the window thread.
self.onmessage = (event: MessageEvent<{ id: number; content: string }>) => {
  const { id, content } = event.data;
  try {
    self.postMessage({ id, document: prepareMarkdownRender(content) });
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : "内容渲染失败" });
  }
};
