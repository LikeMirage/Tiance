import { memo, useMemo } from "react";
import "./html-preview.css";

type HtmlPreviewProps = {
  htmlContent: string;
};

export const HtmlPreview = memo(function HtmlPreview({ htmlContent }: HtmlPreviewProps) {
  const previewDocument = useMemo(() => buildPreviewDocument(htmlContent), [htmlContent]);

  return (
    <iframe
      className="html-preview-frame"
      scrolling="yes"
      srcDoc={previewDocument}
      sandbox=""
      title="HTML Preview"
    />
  );
});

const PREVIEW_HEAD_INJECTION = `
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  html {
    width: 100%;
    height: 100%;
    min-height: 100%;
    overflow: auto !important;
    background: #fff;
  }
  body {
    width: 100%;
    min-width: 100%;
    height: auto;
    min-height: 100vh;
    margin: 0;
    overflow: auto !important;
    background: #fff;
  }
  *, *::before, *::after {
    box-sizing: border-box;
  }
  body > :not(script):not(style):not(link):not(meta) {
    min-width: 100vw;
    min-height: 100vh;
  }
  #root, #app, .app, main {
    min-width: 100vw;
    min-height: 100vh;
  }
</style>`;

function buildPreviewDocument(html: string) {
  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `${PREVIEW_HEAD_INJECTION}</head>`);
  }
  if (/<html[\s>]/i.test(html)) {
    return html.replace(/<html([^>]*)>/i, `<html$1><head>${PREVIEW_HEAD_INJECTION}</head>`);
  }
  return `<!doctype html><html><head>${PREVIEW_HEAD_INJECTION}</head><body>${html}</body></html>`;
}
