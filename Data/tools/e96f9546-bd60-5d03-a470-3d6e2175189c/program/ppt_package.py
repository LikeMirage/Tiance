from __future__ import annotations

from collections import deque
from io import BytesIO
import posixpath
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any
import zipfile

from pptx import Presentation


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

ET.register_namespace("", NS["ct"])
ET.register_namespace("p", NS["p"])
ET.register_namespace("a", NS["a"])
ET.register_namespace("r", NS["r"])


def inspect_package(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slides = ordered_slides(archive)
        return {
            "slide_size": slide_size(archive),
            "slide_parts": len([name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")]),
            "theme_names": theme_names(archive),
            "media_count": len([name for name in names if name.startswith("ppt/media/") and not name.endswith("/")]),
            "chart_count": len([name for name in names if name.startswith("ppt/charts/chart") and name.endswith(".xml")]),
            "has_vba": "ppt/vbaProject.bin" in names,
            "has_custom_xml": any(name.startswith("customXml/") for name in names),
            "slides": [inspect_slide_part(archive, item) for item in slides],
        }


def validate_saved_pptx(path: Path) -> dict[str, Any]:
    missing_required_parts: list[str] = []
    xml_errors: list[dict[str, str]] = []
    broken_relationships: list[dict[str, str]] = []
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing_required_parts = sorted(required - names)
            for name in sorted(names):
                if name.endswith(".xml") or name.endswith(".rels"):
                    try:
                        ET.fromstring(archive.read(name))
                    except ET.ParseError as exc:
                        xml_errors.append({"part": name, "error": str(exc)})

            for rels_name in sorted(name for name in names if name.endswith(".rels")):
                source_part = rels_name_to_source_part(rels_name)
                for rel in read_relationships(archive, rels_name, source_part):
                    if rel.get("is_external"):
                        continue
                    target_part = rel.get("target_part")
                    if isinstance(target_part, str) and target_part not in names:
                        broken_relationships.append(
                            {
                                "source": source_part or "/",
                                "relationship": str(rel.get("id") or ""),
                                "target": target_part,
                            }
                        )
    except zipfile.BadZipFile as exc:
        return {
            "ok": False,
            "reopened": False,
            "slide_count": 0,
            "missing_required_parts": [],
            "xml_errors": [{"part": str(path), "error": str(exc)}],
            "broken_relationships": [],
        }

    reopened = False
    slide_count = 0
    reopen_error = ""
    if not missing_required_parts and not xml_errors and not broken_relationships:
        try:
            prs = Presentation(str(path))
            reopened = True
            slide_count = len(prs.slides)
        except Exception as exc:  # noqa: BLE001
            reopen_error = str(exc) or type(exc).__name__

    ok = not missing_required_parts and not xml_errors and not broken_relationships and reopened
    return {
        "ok": ok,
        "reopened": reopened,
        "slide_count": slide_count,
        "missing_required_parts": missing_required_parts,
        "xml_errors": xml_errors,
        "broken_relationships": broken_relationships,
        "reopen_error": reopen_error,
    }


def prune_unreferenced_parts(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        entries = {item.filename: archive.read(item.filename) for item in archive.infolist() if not item.is_dir()}
        reachable = reachable_package_entries(archive)

    keep_names = {"[Content_Types].xml"} | reachable
    removed_parts = sorted(name for name in entries if name not in keep_names)
    if not removed_parts:
        return {"removed_count": 0, "removed_parts": []}

    updated_entries = dict(entries)
    if "[Content_Types].xml" in updated_entries:
        updated_entries["[Content_Types].xml"] = clean_content_types(updated_entries["[Content_Types].xml"], keep_names)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=str(path.parent)) as tmp_file:
            tmp_path = Path(tmp_file.name)
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as output:
            for name, data in updated_entries.items():
                if name in keep_names:
                    output.writestr(name, data)
        tmp_path.replace(path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return {"removed_count": len(removed_parts), "removed_parts": removed_parts[:50]}


def reachable_package_entries(archive: zipfile.ZipFile) -> set[str]:
    names = set(archive.namelist())
    reachable: set[str] = set()
    queued_parts: deque[str] = deque()

    if "_rels/.rels" in names:
        reachable.add("_rels/.rels")
        for rel in read_relationships(archive, "_rels/.rels", ""):
            target_part = rel.get("target_part")
            if not rel.get("is_external") and isinstance(target_part, str) and target_part in names:
                queued_parts.append(target_part)

    while queued_parts:
        part_name = queued_parts.popleft()
        if part_name in reachable:
            continue
        reachable.add(part_name)
        rels_name = part_to_rels_name(part_name)
        if rels_name not in names:
            continue
        reachable.add(rels_name)
        for rel in read_relationships(archive, rels_name, part_name):
            target_part = rel.get("target_part")
            if rel.get("is_external") or not isinstance(target_part, str):
                continue
            if target_part in names and target_part not in reachable:
                queued_parts.append(target_part)
    return reachable


def clean_content_types(content_types_xml: bytes, keep_names: set[str]) -> bytes:
    root = ET.fromstring(content_types_xml)
    for override in list(root.findall("ct:Override", NS)):
        part_name = str(override.attrib.get("PartName") or "").lstrip("/")
        if part_name and part_name not in keep_names:
            root.remove(override)
    buffer = BytesIO()
    ET.ElementTree(root).write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue()


def inspect_slide_part(archive: zipfile.ZipFile, slide_info: dict[str, Any]) -> dict[str, Any]:
    part_name = str(slide_info["part"])
    root = read_xml(archive, part_name)
    rel_counts = slide_relationship_counts(archive, part_name)
    text = text_from(root)
    return {
        "slide_index": slide_info["slide_index"],
        "part": part_name,
        "hidden": slide_info.get("hidden", False),
        "text_block_count": len(root.findall(".//a:t", NS)),
        "text_character_count": len(text),
        "shape_count": len(root.findall(".//p:sp", NS)),
        "graphic_frame_count": len(root.findall(".//p:graphicFrame", NS)),
        "table_count": len(root.findall(".//a:tbl", NS)),
        "image_relationship_count": rel_counts["images"],
        "chart_relationship_count": rel_counts["charts"],
        "notes_relationship_count": rel_counts["notes"],
        "embedded_object_relationship_count": rel_counts["embedded_objects"],
        "has_notes": rel_counts["notes"] > 0,
    }


def ordered_slides(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    names = set(archive.namelist())
    if "ppt/presentation.xml" not in names or "ppt/_rels/presentation.xml.rels" not in names:
        return fallback_slide_parts(names)

    presentation = read_xml(archive, "ppt/presentation.xml")
    rels = {
        str(rel["id"]): str(rel["target_part"])
        for rel in read_relationships(archive, "ppt/_rels/presentation.xml.rels", "ppt/presentation.xml")
        if not rel.get("is_external") and rel.get("id") and rel.get("target_part")
    }
    slides: list[dict[str, Any]] = []
    for index, slide_id in enumerate(presentation.findall(".//p:sldIdLst/p:sldId", NS)):
        rel_id = slide_id.attrib.get(f"{{{NS['r']}}}id")
        part_name = rels.get(str(rel_id))
        if part_name:
            slides.append(
                {
                    "slide_index": index,
                    "part": part_name,
                    "hidden": slide_id.attrib.get("show") == "0",
                }
            )
    return slides or fallback_slide_parts(names)


def fallback_slide_parts(names: set[str]) -> list[dict[str, Any]]:
    slide_parts = sorted(
        [name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
        key=slide_sort_key,
    )
    return [{"slide_index": index, "part": part_name, "hidden": False} for index, part_name in enumerate(slide_parts)]


def slide_size(archive: zipfile.ZipFile) -> dict[str, int]:
    try:
        root = read_xml(archive, "ppt/presentation.xml")
    except KeyError:
        return {"cx": 0, "cy": 0}
    size = root.find("p:sldSz", NS)
    if size is None:
        return {"cx": 0, "cy": 0}
    return {"cx": int(size.attrib.get("cx", "0")), "cy": int(size.attrib.get("cy", "0"))}


def theme_names(archive: zipfile.ZipFile) -> list[str]:
    values: list[str] = []
    for name in sorted(item for item in archive.namelist() if item.startswith("ppt/theme/theme") and item.endswith(".xml")):
        try:
            root = read_xml(archive, name)
        except ET.ParseError:
            continue
        theme_name = root.attrib.get("name")
        if theme_name:
            values.append(theme_name)
    return values


def slide_relationship_counts(archive: zipfile.ZipFile, slide_part: str) -> dict[str, int]:
    counts = {"images": 0, "charts": 0, "notes": 0, "embedded_objects": 0}
    rels_name = part_to_rels_name(slide_part)
    if rels_name not in archive.namelist():
        return counts
    for rel in read_relationships(archive, rels_name, slide_part):
        rel_type = str(rel.get("type") or "").lower()
        target_part = str(rel.get("target_part") or "").lower()
        if rel_type.endswith("/image") or target_part.startswith("ppt/media/"):
            counts["images"] += 1
        if rel_type.endswith("/chart") or target_part.startswith("ppt/charts/"):
            counts["charts"] += 1
        if rel_type.endswith("/notesslide") or target_part.startswith("ppt/notesslides/"):
            counts["notes"] += 1
        if "oleobject" in rel_type or rel_type.endswith("/package") or target_part.startswith("ppt/embeddings/"):
            counts["embedded_objects"] += 1
    return counts


def read_relationships(archive: zipfile.ZipFile, rels_name: str, source_part: str) -> list[dict[str, Any]]:
    if rels_name not in archive.namelist():
        return []
    root = read_xml(archive, rels_name)
    relationships: list[dict[str, Any]] = []
    for rel in root.findall("rel:Relationship", NS):
        target = str(rel.attrib.get("Target") or "")
        target_mode = rel.attrib.get("TargetMode")
        is_external = target_mode == "External"
        relationships.append(
            {
                "id": rel.attrib.get("Id"),
                "type": rel.attrib.get("Type"),
                "target": target,
                "target_mode": target_mode or "Internal",
                "is_external": is_external,
                "target_part": "" if is_external else resolve_relationship_target(source_part, target),
            }
        )
    return relationships


def resolve_relationship_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base_dir = "" if not source_part else posixpath.dirname(source_part)
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def part_to_rels_name(part_name: str) -> str:
    base_dir = posixpath.dirname(part_name)
    file_name = posixpath.basename(part_name)
    if not base_dir:
        return f"_rels/{file_name}.rels"
    return f"{base_dir}/_rels/{file_name}.rels"


def rels_name_to_source_part(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in rels_name or not rels_name.endswith(".rels"):
        return ""
    base_dir, rel_file = rels_name.split(marker, 1)
    return f"{base_dir}/{rel_file[:-5]}"


def read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(archive.read(name))


def text_from(root: ET.Element) -> str:
    return "".join(item.text or "" for item in root.findall(".//a:t", NS))


def slide_sort_key(name: str) -> tuple[int, str]:
    digits = "".join(char for char in posixpath.basename(name) if char.isdigit())
    return (int(digits) if digits else 0, name)
