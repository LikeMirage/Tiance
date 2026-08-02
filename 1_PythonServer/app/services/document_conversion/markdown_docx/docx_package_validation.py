from __future__ import annotations

import posixpath
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from .omml_validation import find_omml_structure_error
from .word_xml import find_wordprocessingml_order_error

from .docx_package_xml import (
    CONTENT_TYPES_NS,
    ENDNOTE_CONTENT_TYPE,
    ENDNOTE_RELATIONSHIP,
    FOOTNOTE_CONTENT_TYPE,
    FOOTNOTE_RELATIONSHIP,
    RELATIONSHIPS_NS,
    parse_xml,
)


REQUIRED_PARTS = (
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/_rels/document.xml.rels",
)
VALIDATED_WORD_PARTS = (
    "word/document.xml",
    "word/styles.xml",
    "word/settings.xml",
    "word/numbering.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
)


def validate_docx_package(path: Path) -> None:
    with ZipFile(path, "r") as archive:
        entry_names = archive.namelist()
        names = set(entry_names)
        _validate_unique_entries(entry_names, names)
        _validate_required_parts(names)
        damaged_entry = archive.testzip()
        if damaged_entry:
            raise ValueError(f"生成的 DOCX ZIP 条目损坏：{damaged_entry}")

        content_types = parse_xml(
            archive.read("[Content_Types].xml"),
            "[Content_Types].xml",
        )
        document_relationships = parse_xml(
            archive.read("word/_rels/document.xml.rels"),
            "word/_rels/document.xml.rels",
        )
        _validate_content_type_overrides(content_types, names)
        for name in sorted(item for item in names if item.endswith(".rels")):
            _validate_relationship_part(name, archive.read(name), names)
        for name in VALIDATED_WORD_PARTS:
            if name in names:
                _validate_word_xml(name, archive.read(name))

        _validate_note_part_contract(
            content_types,
            document_relationships,
            names,
            part_name="/word/footnotes.xml",
            content_type=FOOTNOTE_CONTENT_TYPE,
            relationship_type=FOOTNOTE_RELATIONSHIP,
        )
        _validate_note_part_contract(
            content_types,
            document_relationships,
            names,
            part_name="/word/endnotes.xml",
            content_type=ENDNOTE_CONTENT_TYPE,
            relationship_type=ENDNOTE_RELATIONSHIP,
        )


def _validate_unique_entries(entry_names: list[str], names: set[str]) -> None:
    if len(entry_names) == len(names):
        return
    duplicate = next(name for name, count in Counter(entry_names).items() if count > 1)
    raise ValueError(f"生成的 DOCX 包含重复 ZIP 条目：{duplicate}")


def _validate_required_parts(names: set[str]) -> None:
    for required in REQUIRED_PARTS:
        if required not in names:
            raise ValueError(f"生成的 DOCX 缺少 {required}。")


def _validate_word_xml(name: str, data: bytes) -> None:
    root = parse_xml(data, name)
    order_error = find_wordprocessingml_order_error(root)
    if order_error:
        raise ValueError(f"生成的 DOCX 包含无效 Word XML 顺序（{name}）：{order_error}")
    structure_error = find_omml_structure_error(root)
    if structure_error:
        raise ValueError(f"生成的 DOCX 包含无效 Word 公式结构：{structure_error}")


def _validate_content_type_overrides(root, names: set[str]) -> None:
    for override in root.findall(f"{{{CONTENT_TYPES_NS}}}Override"):
        part_name = (override.get("PartName") or "").lstrip("/")
        if not part_name:
            raise ValueError("生成的 DOCX 包含空的内容类型 PartName。")
        if part_name not in names:
            raise ValueError(f"生成的 DOCX 内容类型指向不存在的部件：{part_name}")


def _validate_relationship_part(name: str, data: bytes, names: set[str]) -> None:
    root = parse_xml(data, name)
    ids: set[str] = set()
    base_path = _relationship_base_path(name)
    for relationship in root.findall(f"{{{RELATIONSHIPS_NS}}}Relationship"):
        relationship_id = relationship.get("Id") or ""
        if not relationship_id:
            raise ValueError(f"生成的 DOCX 关系缺少 Id：{name}")
        if relationship_id in ids:
            raise ValueError(f"生成的 DOCX 关系 Id 重复：{name}#{relationship_id}")
        ids.add(relationship_id)
        if relationship.get("TargetMode") == "External":
            continue
        target = (relationship.get("Target") or "").split("#", 1)[0]
        if not target:
            raise ValueError(f"生成的 DOCX 关系缺少 Target：{name}#{relationship_id}")
        decoded = unquote(target).replace("\\", "/")
        resolved = (
            posixpath.normpath(decoded.lstrip("/"))
            if decoded.startswith("/")
            else posixpath.normpath(posixpath.join(base_path, decoded))
        )
        if resolved not in names:
            raise ValueError(
                f"生成的 DOCX 关系指向不存在的部件：{name}#{relationship_id} -> {resolved}"
            )


def _relationship_base_path(relationship_name: str) -> str:
    if relationship_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in relationship_name or not relationship_name.endswith(".rels"):
        return posixpath.dirname(relationship_name)
    directory, file_name = relationship_name.split(marker, 1)
    source_name = file_name[: -len(".rels")]
    return posixpath.dirname(posixpath.join(directory, source_name))


def _validate_note_part_contract(
    content_types,
    document_relationships,
    names: set[str],
    *,
    part_name: str,
    content_type: str,
    relationship_type: str,
) -> None:
    archive_name = part_name.lstrip("/")
    if archive_name not in names:
        return
    if not any(
        override.get("PartName") == part_name
        and override.get("ContentType") == content_type
        for override in content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
    ):
        raise ValueError(f"生成的 DOCX 缺少 {part_name} 的正确内容类型。")
    relationship_tag = f"{{{RELATIONSHIPS_NS}}}Relationship"
    for relationship in document_relationships.findall(relationship_tag):
        if relationship.get("Type") != relationship_type:
            continue
        target = unquote(relationship.get("Target") or "").replace("\\", "/")
        resolved = (
            posixpath.normpath(target.lstrip("/"))
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("word", target))
        )
        if resolved == archive_name:
            return
    raise ValueError(f"生成的 DOCX 缺少指向 {part_name} 的正确文档关系。")
