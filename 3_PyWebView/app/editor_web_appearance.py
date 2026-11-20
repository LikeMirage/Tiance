"""Apply the editor backdrop to standard web documents and Bing search results."""

import json
import re
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit


def appearance_palette(mode: str, colors: dict) -> tuple[str, ...]:
    if mode == "original":
        return ("original",)
    if mode not in ("dark", "light"):
        raise ValueError("网页配色模式无效")
    palette = tuple(colors[name] for name in ("background", "text", "accent"))
    if not all(isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in palette):
        raise ValueError("网页主题颜色无效")
    if "scrollbarSize" not in colors:  # Frontends predating themed scrollbars.
        return (mode, *palette)
    size = colors["scrollbarSize"]
    if not isinstance(size, str) or not re.fullmatch(r"[1-9][0-9]?px", size):
        raise ValueError("网页滚动条尺寸无效")
    scrollbar = tuple(colors.get(name) for name in ("scrollbarTrack", "scrollbarThumb", "scrollbarThumbHover"))
    if not all(isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{8}", color) for color in scrollbar):
        raise ValueError("网页滚动条颜色无效")
    return (mode, *palette, size, *scrollbar)


@cache
def _editor_styles(filename: str):
    return (Path(__file__).resolve().parents[1] / "assets/editor" / filename).read_text(encoding="utf-8-sig")


def page_appearance_script(url: str, appearance: tuple[str, ...]) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return None
    bing = parsed.hostname in ("bing.com", "www.bing.com", "cn.bing.com") and parsed.path.rstrip("/") == "/search"
    bing_css = _editor_styles("bing-results.css") if bing else ""
    scrollbar_css = _editor_styles("scrollbars.css") if len(appearance) > 4 else ""
    return f"({_APPLY})(...{json.dumps((appearance, bing_css, scrollbar_css))})"


_APPLY = r"""([mode, background, text, accent, size, track, thumb, hover], bingStyles, scrollbarStyles) => {
    if (window !== window.top || !/^https?:$/.test(location.protocol) || document.contentType !== 'text/html') return;
    const key = Symbol.for('tiance.pageAppearance');
    const previous = document[key];
    if (previous) {
        document.adoptedStyleSheets = document.adoptedStyleSheets.filter(s => s !== previous);
        delete document[key];
        document.documentElement.removeAttribute('data-tiance-web-scrollbars');
    }
    if (mode === 'original' || !document.body) return;
    const bing = ['bing.com', 'www.bing.com', 'cn.bing.com'].includes(location.hostname)
        && location.pathname.replace(/\/$/, '') === '/search' && bingStyles;
    const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
    if (!ctx) return;
    function luminance(color) {
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, 1, 1);
        const [r, g, b] = Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3), channel => {
            const v = channel / 255;
            return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
        });
        return .2126 * r + .7152 * g + .0722 * b;
    }
    const ink = luminance(getComputedStyle(document.body).color);
    const paper = luminance(background);
    const readable = (Math.max(ink, paper) + .05) / (Math.min(ink, paper) + .05) >= 4.5;
    let css = 'html, body {background-color: transparent !important}';
    if (bing) {
        css += bing;
        if (!readable) {
            // Keep richly formatted answers on their original reading surface.
            const surface = ink > .18 ? '#181818' : '#fff';
            css += `#b_context > li, #b_results > li:not(.b_algo), .b_algo :is(.b_rich, .b_ans, .b_vList, .b_vlist2) {background-color: ${surface}}
                #b_tween, #b_tween .sb_count, #b_footer a, #b_header .b_scopebar a,
                #b_results > .b_algo > h2 a, #b_results > .b_algo > .b_title a,
                #b_results > .b_algo .b_caption > p, #b_results > .b_algo .b_attribution {color: ${text} !important}
                #b_results > .b_algo > h2 a, #b_results > .b_algo > .b_title a {color: color-mix(in srgb, ${text} 72%, ${accent}) !important}`;
        }
    } else if (!readable) {
        // Light-only and dark-only sites often depend on the browser's implicit canvas.
        // Preserve explicit site colors, and supply that canvas when it is transparent.
        const rootColor = getComputedStyle(document.documentElement).backgroundColor;
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = rootColor;
        ctx.fillRect(0, 0, 1, 1);
        if (ctx.getImageData(0, 0, 1, 1).data[3] === 255) {
            css = '';
        } else {
            ctx.fillStyle = ink > .18 ? '#181818' : '#fff';
            ctx.fillRect(0, 0, 1, 1);
            ctx.fillStyle = rootColor;
            ctx.fillRect(0, 0, 1, 1);
            const rgb = ctx.getImageData(0, 0, 1, 1).data.slice(0, 3);
            css = `html {background-color: rgb(${rgb.join(' ')}) !important}`;
        }
    }
    if (scrollbarStyles) {
        document.documentElement.setAttribute('data-tiance-web-scrollbars', '');
        css += `:root {--tiance-web-scrollbar-size:${size}; --tiance-web-scrollbar-track:${track};
            --tiance-web-scrollbar-thumb:${thumb}; --tiance-web-scrollbar-hover:${hover}}` + scrollbarStyles;
    }
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    document[key] = sheet;
}"""
