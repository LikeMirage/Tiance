from __future__ import annotations

from base64 import b64encode
from html import escape

import markdown

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportImage,
    PreparedConversationExport,
    RenderedConversationExport,
)
from .markdown import build_conversation_markdown


class HtmlConversationExportRenderer:
    def render(
        self,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        source = build_conversation_markdown(
            prepared,
            selection,
            image_reference=_image_data_url,
        )
        safe_source = escape(source, quote=False)
        body = markdown.markdown(
            safe_source,
            extensions=("extra", "sane_lists"),
            output_format="html5",
        )
        title = escape(
            prepared.document.session.title
            if selection.session_info
            else "会话导出"
        )
        content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ max-width: 920px; margin: 0 auto; padding: 40px 32px 80px; font: 16px/1.7 system-ui, sans-serif; }}
    h1, h2, h3, h4 {{ line-height: 1.35; margin-top: 1.6em; }}
    h2 {{ border-bottom: 1px solid #8885; padding-bottom: .35em; }}
    img {{ display: block; max-width: 100%; height: auto; margin: 1.2em auto; }}
    pre {{ overflow: auto; padding: 14px; border-radius: 6px; background: #8882; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #8886; padding: 6px 10px; text-align: left; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
        return RenderedConversationExport(
            content=content.encode("utf-8"),
            extension=".html",
        )


def _image_data_url(image: ConversationExportImage) -> str:
    encoded = b64encode(image.content).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"
