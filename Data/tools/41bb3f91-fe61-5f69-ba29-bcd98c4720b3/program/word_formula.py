from __future__ import annotations

import re
from functools import lru_cache
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

LATEX_ENVIRONMENT_RE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")

REQUIRED_OMML_CHILDREN = {
    "f": ("num", "den"),
    "func": ("fName", "e"),
    "limLow": ("e", "lim"),
    "limUpp": ("e", "lim"),
    "nary": ("sub", "sup", "e"),
    "rad": ("deg", "e"),
    "sPre": ("sub", "sup", "e"),
    "sSub": ("e", "sub"),
    "sSubSup": ("e", "sub", "sup"),
    "sSup": ("e", "sup"),
}

REQUIRED_OMML_PARENTS = {
    "deg": {"rad"},
    "den": {"f"},
    "fName": {"func"},
    "lim": {"limLow", "limUpp"},
    "mr": {"m"},
    "num": {"f"},
    "sub": {"nary", "sPre", "sSub", "sSubSup"},
    "sup": {"nary", "sPre", "sSubSup", "sSup"},
}


def validate_latex(latex: str) -> str:
    if not _has_balanced_unescaped_braces(latex):
        return "花括号未配对"
    environments: list[str] = []
    for match in LATEX_ENVIRONMENT_RE.finditer(latex):
        operation, environment = match.groups()
        if operation == "begin":
            environments.append(environment)
        elif not environments or environments.pop() != environment:
            return f"LaTeX 环境开始和结束标签不匹配：{environment}"
    if environments:
        return f"LaTeX 环境未闭合：{environments[-1]}"
    if len(re.findall(r"\\left(?![A-Za-z])", latex)) != len(re.findall(r"\\right(?![A-Za-z])", latex)):
        return "\\left 和 \\right 未配对"
    unsupported = re.search(r"\\(tag|label)\s*\{", latex)
    if unsupported is not None:
        return f"暂不支持 \\{unsupported.group(1)}，为避免丢失内容已保留原公式"
    if re.search(r"\\nonumber(?![A-Za-z])", latex):
        return "暂不支持 \\nonumber，为避免丢失内容已保留原公式"
    return ""


def preprocess_latex(latex: str) -> str:
    text = latex.strip()
    text = text.replace("\\displaystyle", "")
    text = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", text)
    text = re.sub(r"[。，、；：]+$", "", text)
    if text.endswith((",", ".")):
        text = text[:-1]
    return text.strip()


def latex_to_word_omml(latex: str, *, xsl_path: Path) -> tuple[Any | None, str]:
    validation_error = validate_latex(latex)
    if validation_error:
        return None, validation_error
    normalized = preprocess_latex(latex)
    if not normalized:
        return None, "公式内容为空。"
    if not xsl_path.is_file():
        return None, f"缺少 MML2OMML.XSL：{xsl_path}"

    try:
        mathml_text = latex_to_mathml(normalized)
        mathml_tree = etree.fromstring(mathml_text.encode("utf-8"))
        residual = _residual_latex_commands(mathml_tree)
        if residual:
            return None, "转换结果仍包含未识别命令：" + "、".join(residual)
        transform = _load_xslt(str(xsl_path), xsl_path.stat().st_mtime_ns)
        omml = transform(mathml_tree)
        root = omml.getroot()
        repair_empty_nary_operands(root)
        _fill_empty_omml_operands(root)
        structure_error = find_omml_structure_error(root)
        if structure_error:
            return None, f"Word 公式结构无效：{structure_error}"
        residual = _residual_latex_commands(root)
        if residual:
            return None, "Word 公式仍包含未识别命令：" + "、".join(residual)
        return root, ""
    except Exception as exc:
        return None, str(exc) or exc.__class__.__name__


def repair_empty_nary_operands(root: Any) -> None:
    for parent in list(root.iter()):
        _repair_empty_nary_operands_in_parent(parent)


@lru_cache(maxsize=4)
def _load_xslt(path: str, modified_time_ns: int) -> Any:
    del modified_time_ns
    return etree.XSLT(etree.parse(path))


def _has_balanced_unescaped_braces(text: str) -> bool:
    depth = 0
    for index, char in enumerate(text):
        if char not in "{}" or _is_escaped(text, index):
            continue
        depth += 1 if char == "{" else -1
        if depth < 0:
            return False
    return depth == 0


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _residual_latex_commands(root: Any) -> list[str]:
    return sorted(set(re.findall(r"\\[A-Za-z]+", "".join(root.itertext()))))


def _fill_empty_omml_operands(root: Any) -> None:
    operand_parents = {f"{OMML}sSub", f"{OMML}sSup", f"{OMML}sSubSup", f"{OMML}nary"}
    for element in root.iter():
        if element.tag not in operand_parents:
            continue
        operand = element.find(f"{OMML}e")
        if operand is None or not _is_empty_container(operand):
            continue
        run = etree.SubElement(operand, f"{OMML}r")
        text = etree.SubElement(run, f"{OMML}t")
        text.text = "\u2060"


def find_omml_structure_error(root: Any) -> str:
    for element in root.iter():
        name = _omml_local_name(element)
        if name is None:
            continue
        parent_names = REQUIRED_OMML_PARENTS.get(name)
        if parent_names is not None:
            parent_name = _omml_local_name(element.getparent())
            if parent_name not in parent_names:
                return f"m:{name} 不能位于 m:{parent_name or 'unknown'} 下"
        required = REQUIRED_OMML_CHILDREN.get(name)
        if required is None:
            continue
        child_names = [child_name for child in element if (child_name := _omml_local_name(child)) is not None]
        positions: list[int] = []
        for child_name in required:
            if child_names.count(child_name) != 1:
                return f"m:{name} 必须包含一个直接子节点 m:{child_name}"
            positions.append(child_names.index(child_name))
        if positions != sorted(positions):
            expected = "、".join(f"m:{child_name}" for child_name in required)
            return f"m:{name} 的必要子节点顺序必须为 {expected}"
    return ""


def _omml_local_name(element: Any) -> str | None:
    if element is None or not isinstance(element.tag, str):
        return None
    qualified = etree.QName(element)
    return qualified.localname if qualified.namespace == OMML_NS else None


def _is_empty_container(element: Any) -> bool:
    return len(element) == 0 and not (element.text or "").strip()


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
