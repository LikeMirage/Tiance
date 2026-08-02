from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from latex2mathml.converter import convert as latex_to_mathml
from lxml import etree

from .mathml_styles import normalize_mathml_styles
from .omml_validation import find_omml_structure_error
from .text_scanning import is_escaped

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OMML = f"{{{OMML_NS}}}"

ENVIRONMENT_REPLACEMENTS = [
    (r"\\begin\{aligned\}", r"\\begin{align*}"),
    (r"\\end\{aligned\}", r"\\end{align*}"),
    (r"\\begin\{eqnarray\}", r"\\begin{align*}"),
    (r"\\end\{eqnarray\}", r"\\end{align*}"),
    (r"\\begin\{alignat\}\{(\d+)\}", r"\\begin{align*}"),
    (r"\\end\{alignat\}", r"\\end{align*}"),
    (r"\\begin\{tabular\}", r"\\begin{array}"),
    (r"\\end\{tabular\}", r"\\end{array}"),
]

SYMBOL_FIXES = [
    ("\\Longleftrightarrow", "⟺"),
    ("\\Leftrightarrow", "⇔"),
    ("\\Longrightarrow", "⟹"),
    ("\\longrightarrow", "⟶"),
    ("\\longleftarrow", "⟵"),
    ("\\rightarrow", "→"),
    ("\\leftarrow", "←"),
    ("\\Rightarrow", "⇒"),
    ("\\arg\\max", "\\operatorname{argmax}"),
    ("\\arg\\min", "\\operatorname{argmin}"),
    ("\\argmax", "\\operatorname{argmax}"),
    ("\\argmin", "\\operatorname{argmin}"),
    ("\\csch", "\\operatorname{csch}"),
    ("\\sech", "\\operatorname{sech}"),
    ("\\supseteq", "⊇"),
    ("\\subseteq", "⊆"),
    ("\\setminus", "∖"),
    ("\\approx", "≈"),
    ("\\propto", "∝"),
    ("\\equiv", "≡"),
    ("\\simeq", "≃"),
    ("\\notin", "∉"),
    ("\\neg", "¬"),
    ("\\lor", "∨"),
    ("\\land", "∧"),
    ("\\gg", "≫"),
    ("\\ll", "≪"),
    ("\\mp", "∓"),
    ("\\pm", "±"),
    ("\\div", "÷"),
    ("\\times", "×"),
    ("\\cdot", "⋅"),
    ("\\circ", "∘"),
    ("\\cdots", "⋯"),
    ("\\ddots", "⋱"),
    ("\\vdots", "⋮"),
    ("\\ldots", "…"),
    ("\\dots", "…"),
    ("\\star", "⋆"),
    ("\\sim", "∼"),
    ("\\neq", "≠"),
    ("\\leq", "≤"),
    ("\\geq", "≥"),
    ("\\to", "→"),
    ("\\in", "∈"),
    ("\\ni", "∋"),
    ("\\wp", "℘"),
    ("\\Im", "ℑ"),
    ("\\Re", "ℜ"),
    ("\\aleph", "ℵ"),
    ("\\nabla", "∇"),
    ("\\forall", "∀"),
    ("\\exists", "∃"),
    ("\\infty", "∞"),
    ("\\partial", "∂"),
    ("\\subset", "⊂"),
    ("\\supset", "⊃"),
    ("\\cup", "∪"),
    ("\\cap", "∩"),
    ("\\emptyset", "∅"),
    ("\\bullet", "∙"),
    ("\\oplus", "⊕"),
    ("\\otimes", "⊗"),
    ("\\odot", "⊙"),
    ("\\Box", "□"),
    ("\\Diamond", "◇"),
    ("\\triangle", "△"),
    ("\\angle", "∠"),
    ("\\perp", "⊥"),
    ("\\parallel", "∥"),
    ("\\mid", "∣"),
    ("\\qquad", "    "),
    ("\\quad", "  "),
    ("\\,", " "),
    ("\\;", " "),
    ("\\!", ""),
]

SYMBOL_FIX_MAP = dict(SYMBOL_FIXES)
SYMBOL_FIX_RE = re.compile(
    "|".join(
        (
            rf"{re.escape(command)}(?![A-Za-z])"
            if command[-1].isalpha()
            else re.escape(command)
        )
        for command in sorted(SYMBOL_FIX_MAP, key=len, reverse=True)
    )
)
LATEX_ENVIRONMENT_RE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")


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
    if len(re.findall(r"\\left(?![A-Za-z])", latex)) != len(
        re.findall(r"\\right(?![A-Za-z])", latex)
    ):
        return "\\left 和 \\right 未配对"
    unsupported = re.search(r"\\(tag|label)\s*\{", latex)
    if unsupported is not None:
        return f"暂不支持 \\{unsupported.group(1)}，为避免丢失内容已保留原公式"
    if re.search(r"\\nonumber(?![A-Za-z])", latex):
        return "暂不支持 \\nonumber，为避免丢失内容已保留原公式"
    return ""


def preprocess_latex(latex: str) -> str:
    text = latex.strip()
    for pattern, replacement in ENVIRONMENT_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    text = SYMBOL_FIX_RE.sub(lambda match: SYMBOL_FIX_MAP[match.group(0)], text)
    return text.strip()


def latex_to_omml(
    latex: str,
    *,
    style_notices: list[str] | None = None,
) -> tuple[Any | None, str]:
    xsl_path = _resolve_xsl_path()
    if not xsl_path.is_file():
        return None, f"缺少 MML2OMML.XSL：{xsl_path}"
    try:
        mathml_text = latex_to_mathml(latex)
        mathml_tree = etree.fromstring(mathml_text.encode("utf-8"))
        unsupported_colors = normalize_mathml_styles(mathml_tree)
        if style_notices is not None:
            style_notices.extend(
                f"暂不支持颜色 {color}，已保留数学内容并忽略颜色"
                for color in unsupported_colors
            )
        residual = _residual_latex_commands(mathml_tree)
        if residual:
            return None, "转换结果仍包含未识别命令：" + "、".join(residual)
        transform = _load_xslt(str(xsl_path), xsl_path.stat().st_mtime_ns)
        root = transform(mathml_tree).getroot()
        _repair_empty_nary_operands(root)
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


def _resolve_xsl_path() -> Path:
    module_root = Path(__file__).resolve().parent
    local_path = module_root / "assets" / "MML2OMML.XSL"
    if local_path.is_file():
        return local_path
    return module_root.parent / "assets" / "MML2OMML.XSL"


@lru_cache(maxsize=4)
def _load_xslt(path: str, modified_time_ns: int) -> Any:
    del modified_time_ns
    return etree.XSLT(etree.parse(path))


def _has_balanced_unescaped_braces(text: str) -> bool:
    depth = 0
    for index, char in enumerate(text):
        if char not in "{}" or is_escaped(text, index):
            continue
        depth += 1 if char == "{" else -1
        if depth < 0:
            return False
    return depth == 0


def _residual_latex_commands(root: Any) -> list[str]:
    text = "".join(root.itertext())
    return sorted(set(re.findall(r"\\[A-Za-z]+", text)))


def _repair_empty_nary_operands(root: Any) -> None:
    for parent in list(root.iter()):
        index = len(parent) - 1
        while index >= 0:
            nary = parent[index]
            if nary.tag == f"{OMML}nary":
                operand = nary.find(f"{OMML}e")
                if operand is not None and _is_empty_omml_container(operand):
                    for node in _take_following_operand_nodes(parent, index + 1):
                        operand.append(node)
            index -= 1


def _fill_empty_omml_operands(root: Any) -> None:
    operand_parents = {f"{OMML}sSub", f"{OMML}sSup", f"{OMML}sSubSup", f"{OMML}nary"}
    for element in root.iter():
        if element.tag not in operand_parents:
            continue
        operand = element.find(f"{OMML}e")
        if operand is None or not _is_empty_omml_container(operand):
            continue
        run = etree.SubElement(operand, f"{OMML}r")
        text = etree.SubElement(run, f"{OMML}t")
        text.text = "\u2060"


def _is_empty_omml_container(element: Any) -> bool:
    return len(element) == 0 and not (element.text or "").strip()


def _take_following_operand_nodes(parent: Any, start: int) -> list[Any]:
    boundaries = {"+", "-", "−", "=", "≈", "≠", "<", ">", "≤", "≥", ",", ";", "；", "，"}
    structural_boundaries = {
        f"{OMML}deg",
        f"{OMML}den",
        f"{OMML}e",
        f"{OMML}fName",
        f"{OMML}lim",
        f"{OMML}m",
        f"{OMML}mr",
        f"{OMML}num",
        f"{OMML}sub",
        f"{OMML}sup",
    }
    nodes: list[Any] = []
    index = start
    while index < len(parent):
        candidate = parent[index]
        if candidate.tag in structural_boundaries:
            break
        if "".join(candidate.itertext()).strip() in boundaries:
            break
        nodes.append(candidate)
        parent.remove(candidate)
    return nodes
