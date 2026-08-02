from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from latex2mathml.converter import convert as latex_to_mathml
from lxml import etree


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OMML = f"{{{OMML_NS}}}"

NARY_OPERAND_BOUNDARY_TEXT = {
    "+",
    "-",
    "−",
    "=",
    "≈",
    "≠",
    "<",
    ">",
    "≤",
    "≥",
    ",",
    ";",
    "；",
    "，",
}


def preprocess_latex(latex: str) -> str:
    text = latex.strip()
    text = re.sub(r"\\tag\{[^}]*\}", "", text)
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = text.replace("\\nonumber", "")
    text = text.replace("\\displaystyle", "")
    text = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", text)
    text = re.sub(r"[。，、；：]+$", "", text)
    if text.endswith((",", ".")):
        text = text[:-1]
    return text.strip()


def latex_to_word_omml(latex: str, *, xsl_path: Path) -> tuple[Any | None, str]:
    normalized = preprocess_latex(latex)
    if not normalized:
        return None, "公式内容为空。"
    if not xsl_path.is_file():
        return None, f"缺少 MML2OMML.XSL：{xsl_path}"

    try:
        mathml_text = latex_to_mathml(normalized)
        mathml_tree = etree.fromstring(mathml_text.encode("utf-8"))
        xslt = etree.parse(str(xsl_path))
        transform = etree.XSLT(xslt)
        omml = transform(mathml_tree)
        root = omml.getroot()
        repair_empty_nary_operands(root)
        return root, ""
    except Exception as exc:
        return None, str(exc) or exc.__class__.__name__


def repair_empty_nary_operands(root: Any) -> None:
    for parent in list(root.iter()):
        _repair_empty_nary_operands_in_parent(parent)


def _repair_empty_nary_operands_in_parent(parent: Any) -> None:
    index = len(parent) - 1
    while index >= 0:
        child = parent[index]
        if _is_nary_with_empty_operand(child):
            operand = child.find(f"{OMML}e")
            if operand is not None:
                for node in _take_following_operand_nodes(parent, index + 1):
                    operand.append(node)
        index -= 1


def _is_nary_with_empty_operand(element: Any) -> bool:
    if element.tag != f"{OMML}nary":
        return False
    operand = element.find(f"{OMML}e")
    return operand is not None and len(operand) == 0 and not (operand.text or "").strip()


def _take_following_operand_nodes(parent: Any, start_index: int) -> list[Any]:
    nodes: list[Any] = []
    index = start_index
    while index < len(parent):
        candidate = parent[index]
        if _is_nary_operand_boundary(candidate):
            break
        nodes.append(candidate)
        parent.remove(candidate)
    return nodes


def _is_nary_operand_boundary(element: Any) -> bool:
    text = "".join(element.itertext()).strip()
    return text in NARY_OPERAND_BOUNDARY_TEXT
