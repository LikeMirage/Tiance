from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import re
import unicodedata
from typing import Any

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from word_elements import FORMULA_XSL_PATH
from word_errors import WordOperationError
from word_formula import latex_to_word_omml, preprocess_latex


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OMATH_TAG = f"{{{OMML_NS}}}oMath"
M_T = f"{{{OMML_NS}}}t"
W_P = qn("w:p")
W_TBL = qn("w:tbl")

FORMULA_WRAPPER_RE = re.compile(
    r"^\s*(?:\$\$(.+)\$\$|\$(.+)\$|\\\((.+)\\\)|\\\[(.+)\\\])\s*$",
    re.DOTALL,
)
FORMULA_REFERENCE_RE = re.compile(r"^formula:([0-9a-f]{16})$")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class FormulaNode:
    reference: str
    index: int
    paragraph_element: Any
    element: Any
    text: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class FormulaMatch:
    node: FormulaNode
    strategy: str


def parse_formula_anchor(value: str) -> str | None:
    """Return LaTeX when an anchor is explicitly formatted as a formula."""

    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    wrapped = FORMULA_WRAPPER_RE.match(stripped)
    if wrapped is not None:
        latex = next(group for group in wrapped.groups() if group is not None)
        return preprocess_latex(latex)
    if _looks_like_raw_latex(stripped):
        return preprocess_latex(stripped)
    return None


def collect_formula_nodes(doc: Any) -> list[FormulaNode]:
    nodes: list[FormulaNode] = []
    fingerprint_occurrences: dict[str, int] = {}
    for _location, paragraph_element, _formula_ordinal, omath in _iter_document_formulas(doc):
        index = len(nodes) + 1
        fingerprint = omml_fingerprint(omath)
        fingerprint_occurrences[fingerprint] = fingerprint_occurrences.get(fingerprint, 0) + 1
        reference_digest = hashlib.sha256(
            f"{fingerprint}:{fingerprint_occurrences[fingerprint]}".encode("utf-8")
        ).hexdigest()[:16]
        nodes.append(
            FormulaNode(
                reference=f"formula:{reference_digest}",
                index=index,
                paragraph_element=paragraph_element,
                element=omath,
                text=formula_text(omath),
                fingerprint=fingerprint,
            )
        )
    return nodes


def resolve_formula_reference(doc: Any, reference: str) -> FormulaNode:
    match = FORMULA_REFERENCE_RE.fullmatch(reference.strip())
    if match is None:
        raise WordOperationError(
            "INVALID_SELECTION",
            "selection.formula_ref 必须使用 inspect 返回的稳定公式引用。",
        )
    nodes = collect_formula_nodes(doc)
    node = next((item for item in nodes if item.reference == reference), None)
    if node is not None:
        return node
    raise WordOperationError(
        "SELECTION_NOT_FOUND",
        f"公式引用不存在或公式内容已变化：{reference}。请局部 inspect 后重试。",
    )


def find_formula_match(doc: Any, latex: str, *, occurrence: int = 1) -> FormulaMatch:
    target_omml = formula_omml_from_latex(latex)
    target_fingerprint = omml_fingerprint(target_omml)
    target_text = formula_text(target_omml)
    nodes = collect_formula_nodes(doc)

    exact = [node for node in nodes if node.fingerprint == target_fingerprint]
    if len(exact) >= occurrence:
        return FormulaMatch(exact[occurrence - 1], "exact")

    text_matches = [node for node in nodes if node.text == target_text]
    if len(text_matches) >= occurrence:
        return FormulaMatch(text_matches[occurrence - 1], "formula_text")

    qualifier = f"（第 {occurrence} 处）" if occurrence > 1 else ""
    candidates = closest_formula_candidates(nodes, target_text)
    hint = "请先 inspect 文档并使用 formula_ref 精确定位。"
    if candidates:
        hint += " 接近候选：" + "；".join(
            f"{node.reference}={display_formula_text(node.text)}" for node in candidates
        )
    raise WordOperationError(
        "SELECTION_NOT_FOUND",
        f"未找到与公式锚点匹配的 Word 公式{qualifier}：{latex}。{hint}",
    )


def formula_omml_from_latex(latex: str, *, xsl_path: Path | None = None) -> Any:
    path = xsl_path or FORMULA_XSL_PATH
    omml, error = latex_to_word_omml(latex, xsl_path=path)
    if omml is None:
        raise WordOperationError(
            "FORMULA_CONVERSION_FAILED",
            f"公式无法转换为 Word 原生公式：{error}",
        )
    return omml


def formula_fingerprint_from_latex(latex: str, *, xsl_path: Path | None = None) -> str:
    return omml_fingerprint(formula_omml_from_latex(latex, xsl_path=xsl_path))


def omml_fingerprint(root: Any) -> str:
    """Normalize stable OMML structure while ignoring presentation properties."""

    clone = deepcopy(root)
    _strip_ignorable_omml(clone)
    return f"{_structure_signature(clone)}|{formula_text(clone)}"


def formula_text(root: Any) -> str:
    return WHITESPACE_RE.sub("", "".join(root.itertext()))


def normalized_formula_text(value: str) -> str:
    return unicodedata.normalize("NFKC", WHITESPACE_RE.sub("", value))


def closest_formula_candidates(nodes: list[FormulaNode], target_text: str) -> list[FormulaNode]:
    normalized_target = normalized_formula_text(target_text)
    ranked = sorted(
        nodes,
        key=lambda node: SequenceMatcher(
            None,
            normalized_target,
            normalized_formula_text(node.text),
        ).ratio(),
        reverse=True,
    )
    return ranked[:3]


def display_formula_text(value: str, *, limit: int = 100) -> str:
    if not value:
        return "<空公式>"
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _iter_document_formulas(doc: Any) -> list[tuple[str, Any, int, Any]]:
    hits: list[tuple[str, Any, int, Any]] = []
    seen_paragraphs: set[Any] = set()
    table_index = 0
    for body_index, block in enumerate(doc.element.body.iterchildren()):
        if block.tag == W_P:
            hits.extend(
                (f"body:{body_index}", block, ordinal, node)
                for ordinal, node in enumerate(_top_level_omath_nodes(block), start=1)
            )
            continue
        if block.tag != W_TBL:
            continue
        table = Table(block, doc)
        for row_index, row in enumerate(table.rows):
            for column_index, cell in enumerate(row.cells):
                for paragraph_index, paragraph in enumerate(cell.paragraphs):
                    if paragraph._p in seen_paragraphs:
                        continue
                    seen_paragraphs.add(paragraph._p)
                    hits.extend(
                        (
                            f"table:{table_index}:{row_index}:{column_index}:{paragraph_index}",
                            paragraph._p,
                            ordinal,
                            node,
                        )
                        for ordinal, node in enumerate(
                            _top_level_omath_nodes(paragraph._p), start=1
                        )
                    )
        table_index += 1
    return hits


def _top_level_omath_nodes(paragraph_element: Any) -> list[Any]:
    nodes: list[Any] = []
    for node in paragraph_element.iter():
        if node.tag != OMATH_TAG:
            continue
        parent = node.getparent()
        if any(ancestor.tag == OMATH_TAG for ancestor in node.iterancestors() if ancestor is not paragraph_element):
            continue
        if parent is not None:
            nodes.append(node)
    return nodes


def _strip_ignorable_omml(root: Any) -> None:
    ignorable_local = {"rPr", "ctrlPr", "argPr", "sty", "jc"}
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue
        local = etree.QName(element).localname
        if local in ignorable_local:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
            continue
        if element.tag == M_T and element.text:
            element.text = WHITESPACE_RE.sub("", element.text)


def _structure_signature(root: Any) -> str:
    parts: list[str] = []

    def walk(element: Any) -> None:
        if not isinstance(element.tag, str):
            return
        qname = etree.QName(element)
        if qname.namespace != OMML_NS:
            return
        local = qname.localname
        if local in {"rPr", "ctrlPr", "argPr", "sty", "jc"}:
            return
        parts.append(local)
        for child in element:
            walk(child)

    walk(root)
    return "/".join(parts)


def _looks_like_raw_latex(text: str) -> bool:
    if text.startswith("\\"):
        return True
    return bool(re.search(r"\\[A-Za-z]+", text)) and any(
        token in text for token in ("{", "^", "_", "\\frac", "\\sum", "\\int")
    )
