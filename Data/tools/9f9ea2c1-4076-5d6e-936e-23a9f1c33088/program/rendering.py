"""Rasterize local SVGs and make readable numbered contact sheets."""
from __future__ import annotations

import io
import math
import re
from xml.etree import ElementTree as ET

ET.register_namespace("", "http://www.w3.org/2000/svg")


def styled_svg(raw: bytes, color: str | None) -> bytes:
    root = ET.fromstring(raw)
    # Resolve currentColor for standalone SVG/PPT consumers. Fixed fills/strokes stay intact.
    resolved = color or root.get("color", "#000000")
    root.set("color", resolved)
    for node in root.iter():
        for key, value in list(node.attrib.items()):
            if "currentcolor" in value.casefold():
                node.set(key, re.sub("currentcolor", resolved, value, flags=re.I))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def rasterize(svg: bytes, size: int):
    from PIL import Image
    import resvg_py

    root = ET.fromstring(svg)
    _, _, width, height = (float(v) for v in root.attrib["viewBox"].split())
    scale = size / max(width, height)
    render_width, render_height = max(1, round(width * scale)), max(1, round(height * scale))
    png = resvg_py.svg_to_bytes(svg_string=svg.decode("utf-8"), width=render_width, height=render_height)
    with Image.open(io.BytesIO(png)) as source:
        icon = source.convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(icon, ((size - icon.width) // 2, (size - icon.height) // 2))
    return canvas


def wrap_label(text: str, font, width: int) -> list[str]:
    """Wrap complete IDs, including long words; never silently ellipsize identity."""
    lines, line = [], ""
    for char in text:
        if line and font.getlength(line + char) > width:
            lines.append(line)
            line = ""
        line += char
    lines.append(line)
    return lines


def contact_sheet(catalog, records: list[dict], *, columns: int | None, color: str | None):
    from PIL import Image, ImageDraw, ImageFont

    cols = min(columns or min(5, math.ceil(math.sqrt(len(records)))), len(records))
    cell_width, icon_size, padding, line_height = 248, 128, 16, 19
    font, title_font = ImageFont.load_default(size=14), ImageFont.load_default(size=16)
    labels = []
    for index, record in enumerate(records, 1):
        labels.append([
            (line, title_font) for line in wrap_label(f"{index:02d}. {record['name']}", title_font, cell_width - 2 * padding)
        ] + [(line, font) for line in wrap_label(
            f"{catalog.libraries[record['library']]['name']} | {record['style']}", font, cell_width - 2 * padding
        )] + [(line, font) for line in wrap_label(record["id"], font, cell_width - 2 * padding)])
    row_heights = [icon_size + 3 * padding + line_height * max(len(label) for label in labels[i:i + cols])
                   for i in range(0, len(records), cols)]
    canvas = Image.new("RGB", (cell_width * cols, sum(row_heights)), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    y, placements = 0, []
    for row, row_height in enumerate(row_heights):
        for col in range(cols):
            index = row * cols + col
            if index >= len(records):
                break
            record, x = records[index], col * cell_width
            draw.rectangle((x, y, x + cell_width - 1, y + row_height - 1), outline="#d7dce4", width=1)
            image_x, image_y = x + (cell_width - icon_size) // 2, y + padding
            for yy in range(0, icon_size, 16):
                for xx in range(0, icon_size, 16):
                    shade = "#dce2ea" if (xx // 16 + yy // 16) % 2 == 0 else "#8895a8"
                    draw.rectangle((image_x + xx, image_y + yy, image_x + xx + 15, image_y + yy + 15), fill=shade)
            icon = rasterize(styled_svg(catalog.svg(record), color), icon_size)
            canvas.paste(icon, (image_x, image_y), icon)
            label_y = image_y + icon_size + padding
            for line, selected_font in labels[index]:
                draw.text((x + padding, label_y), line, font=selected_font, fill="#172131")
                label_y += line_height
            placements.append({"number": index + 1, "id": record["id"], "row": row + 1, "column": col + 1})
        y += row_height
    return canvas, placements, cols
