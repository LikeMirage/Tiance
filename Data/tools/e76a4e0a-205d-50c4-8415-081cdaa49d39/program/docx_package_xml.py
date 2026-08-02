from __future__ import annotations

from lxml import etree


CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
FOOTNOTE_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
)
ENDNOTE_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
)
FOOTNOTE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)
ENDNOTE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
)


def parse_xml(data: bytes, name: str):
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"生成的 DOCX XML 无效：{name}：{exc}") from exc


def serialize_xml(root) -> bytes:
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
    )
