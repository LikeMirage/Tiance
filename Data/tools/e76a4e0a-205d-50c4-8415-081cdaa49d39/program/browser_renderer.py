from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from browser_capture import render_html_page_png


ASSETS_ROOT = Path(__file__).resolve().parents[1] / "assets"
MERMAID_JS_PATH = ASSETS_ROOT / "mermaid.min.js"
KATEX_ROOT = ASSETS_ROOT / "katex"
KATEX_JS_PATH = KATEX_ROOT / "katex.min.js"
KATEX_CSS_PATH = KATEX_ROOT / "katex.min.css"
KATEX_MHCHEM_JS_PATH = KATEX_ROOT / "mhchem.min.js"
TOTAL_BROWSER_RENDER_BUDGET_SECONDS = 40.0
PER_RENDER_TIMEOUT_SECONDS = 10.0


class BrowserRenderBudget:
    def __init__(self, total_seconds: float = TOTAL_BROWSER_RENDER_BUDGET_SECONDS) -> None:
        self._remaining_seconds = max(0.0, total_seconds)

    def render(self, page: str, output_path: Path) -> None:
        if self._remaining_seconds < 1.0:
            raise TimeoutError("本次文档的浏览器渲染总预算已用完。")
        timeout = min(PER_RENDER_TIMEOUT_SECONDS, self._remaining_seconds)
        started_at = time.monotonic()
        try:
            render_html_page_png(page, output_path, timeout_seconds=timeout)
        finally:
            elapsed = max(0.0, time.monotonic() - started_at)
            self._remaining_seconds = max(0.0, self._remaining_seconds - elapsed)


def render_mermaid_png(
    code: str,
    output_path: Path,
    *,
    budget: BrowserRenderBudget | None = None,
) -> None:
    source = code.strip()
    if not source:
        raise ValueError("Mermaid 内容为空。")
    if not MERMAID_JS_PATH.is_file():
        raise FileNotFoundError(f"缺少 mermaid.min.js：{MERMAID_JS_PATH}")
    code_json = json.dumps(source, ensure_ascii=False).replace("</", "<\\/")
    mermaid_uri = MERMAID_JS_PATH.as_uri()
    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src file: 'unsafe-inline'; font-src file: data:;">
  <style>
    html, body {{ margin: 0; padding: 0; background: #ffffff; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }}
    #capture {{ display: inline-block; padding: 24px; background: #ffffff; }}
    #diagram svg {{ display: block; max-width: none; background: #ffffff; }}
  </style>
</head>
<body>
  <div id="capture"><div id="diagram"></div></div>
  <script src="{mermaid_uri}"></script>
  <script>
    const mermaidCode = {code_json};
    (async () => {{
      try {{
        globalThis.mermaid.initialize({{
          startOnLoad: false,
          securityLevel: "strict",
          theme: "default",
          themeVariables: {{ fontFamily: "Microsoft YaHei, Segoe UI, Arial, sans-serif", background: "#ffffff" }}
        }});
        await globalThis.mermaid.parse(mermaidCode);
        const result = await globalThis.mermaid.render("md2docx-mermaid", mermaidCode);
        document.querySelector("#diagram").innerHTML = result.svg;
        markReady();
      }} catch (error) {{ document.body.dataset.error = error && error.message ? error.message : String(error); }}
    }})();
    function markReady() {{
      const rect = document.querySelector("#capture").getBoundingClientRect();
      document.body.dataset.ready = "true";
      document.body.dataset.width = String(Math.ceil(rect.width));
      document.body.dataset.height = String(Math.ceil(rect.height));
    }}
  </script>
</body>
</html>"""
    _render_page(page, output_path, budget)


def render_katex_png(
    latex: str,
    output_path: Path,
    *,
    display_mode: bool = True,
    budget: BrowserRenderBudget | None = None,
) -> None:
    source = latex.strip()
    if not source:
        raise ValueError("公式内容为空。")
    required_assets = (KATEX_JS_PATH, KATEX_CSS_PATH, KATEX_MHCHEM_JS_PATH)
    missing = [str(path) for path in required_assets if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少 KaTeX 资源：" + "、".join(missing))
    source_json = json.dumps(source, ensure_ascii=False).replace("</", "<\\/")
    display_mode_json = "true" if display_mode else "false"
    capture_padding = "12px 16px" if display_mode else "2px 3px"
    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src file: 'unsafe-inline'; font-src file: data:; script-src file: 'unsafe-inline';">
  <link rel="stylesheet" href="{KATEX_CSS_PATH.as_uri()}">
  <style>
    html, body {{ margin: 0; padding: 0; background: #ffffff; color: #111111; }}
    #capture {{ display: inline-block; box-sizing: border-box; padding: {capture_padding}; background: #ffffff; }}
    .katex-display {{ margin: 0; }}
  </style>
</head>
<body>
  <div id="capture"><div id="formula"></div></div>
  <script src="{KATEX_JS_PATH.as_uri()}"></script>
  <script src="{KATEX_MHCHEM_JS_PATH.as_uri()}"></script>
  <script>
    const formulaSource = {source_json};
    (async () => {{
      try {{
        globalThis.katex.render(formulaSource, document.querySelector("#formula"), {{
          displayMode: {display_mode_json}, throwOnError: true, strict: "error", trust: false
        }});
        if (document.fonts && document.fonts.ready) {{ await document.fonts.ready; }}
        const rect = document.querySelector("#capture").getBoundingClientRect();
        document.body.dataset.ready = "true";
        document.body.dataset.width = String(Math.ceil(rect.width));
        document.body.dataset.height = String(Math.ceil(rect.height));
      }} catch (error) {{ document.body.dataset.error = error && error.message ? error.message : String(error); }}
    }})();
  </script>
</body>
</html>"""
    _render_page(page, output_path, budget)


def render_html_png(
    html_fragment: str,
    output_path: Path,
    *,
    base_path: Path | None = None,
    budget: BrowserRenderBudget | None = None,
) -> None:
    source = html_fragment.strip()
    if not source:
        raise ValueError("HTML 内容为空。")
    base_element = ""
    if base_path is not None:
        base_uri = base_path.resolve(strict=False).as_uri().rstrip("/") + "/"
        base_element = f'<base href="{html.escape(base_uri, quote=True)}">'
    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  {base_element}
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: file:; style-src 'unsafe-inline'; font-src data: file:; script-src 'unsafe-inline';">
  <style>
    html, body {{ margin: 0; padding: 0; background: #ffffff; color: #111827; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; font-size: 16px; line-height: 1.55; }}
    #capture {{ display: inline-block; box-sizing: border-box; max-width: 960px; padding: 16px; background: #ffffff; }}
    #capture table {{ border-collapse: collapse; width: max-content; max-width: 100%; }}
    #capture th, #capture td {{ padding: 6px 10px; border: 1px solid #d0d7de; vertical-align: top; }}
    #capture th {{ background: #f6f8fa; font-weight: 700; }}
    #capture img {{ max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <div id="capture">{source}</div>
  <script>
    (async () => {{
      const finish = () => {{
        try {{
          const rect = document.querySelector("#capture").getBoundingClientRect();
          document.body.dataset.ready = "true";
          document.body.dataset.width = String(Math.ceil(rect.width));
          document.body.dataset.height = String(Math.ceil(rect.height));
        }} catch (error) {{ document.body.dataset.error = error && error.message ? error.message : String(error); }}
      }};
      const images = Array.from(document.images || []);
      await Promise.all(images.map((image) => {{
        if (image.complete) {{ return image.decode ? image.decode().catch(() => undefined) : undefined; }}
        return new Promise((resolve) => {{ image.addEventListener("load", resolve, {{ once: true }}); image.addEventListener("error", resolve, {{ once: true }}); }});
      }}));
      if (document.fonts && document.fonts.ready) {{ await document.fonts.ready; }}
      finish(); requestAnimationFrame(finish); setTimeout(finish, 100);
    }})();
  </script>
</body>
</html>"""
    _render_page(page, output_path, budget)


def sanitize_html_fragment(fragment: str) -> str:
    text = re.sub(
        r"<\s*(script|iframe|object|embed|link|meta|base)\b[^>]*>.*?</\s*\1\s*>",
        "",
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<\s*(script|iframe|object|embed|link|meta|base)\b[^>]*/?\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+on[a-zA-Z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\s+(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2",
        r' \1="#"',
        text,
        flags=re.IGNORECASE,
    )


def _render_page(
    page: str,
    output_path: Path,
    budget: BrowserRenderBudget | None,
) -> None:
    if budget is not None:
        budget.render(page, output_path)
        return
    render_html_page_png(
        page,
        output_path,
        timeout_seconds=PER_RENDER_TIMEOUT_SECONDS,
    )
