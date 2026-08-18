from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from formula_converter import (
    LatexPresentation,
    extract_latex_presentation,
    latex_to_omml,
    preprocess_latex as preprocess_formula_latex,
    validate_latex as validate_formula_latex,
)
from latex_extensions import needs_image_rendering, normalize_for_omml


@dataclass(frozen=True, slots=True)
class WordFormulaConversion:
    omml: Any | None
    error: str
    presentation: LatexPresentation | None
    notices: tuple[str, ...]


def validate_latex(latex: str) -> str:
    presentation, error = extract_latex_presentation(latex.strip())
    if presentation is None:
        return error
    return validate_formula_latex(presentation.body)


def preprocess_latex(latex: str) -> str:
    presentation, _error = extract_latex_presentation(latex.strip())
    if presentation is None:
        return latex.strip()
    compatible, _notices = normalize_for_omml(presentation.body)
    return preprocess_formula_latex(compatible)


def convert_latex_to_word_formula(latex: str) -> WordFormulaConversion:
    original = latex.strip()
    if not original:
        return WordFormulaConversion(None, "公式内容为空。", None, ())

    presentation, presentation_error = extract_latex_presentation(original)
    if presentation is None:
        return WordFormulaConversion(None, presentation_error, None, ())

    validation_error = validate_formula_latex(presentation.body)
    if validation_error:
        return WordFormulaConversion(
            None,
            validation_error,
            presentation,
            (),
        )

    if needs_image_rendering(presentation.body):
        return WordFormulaConversion(
            None,
            "该扩展公式需要图片渲染；Word 编辑工具只写入可编辑的原生公式，请改用 Markdown 转 Word。",
            presentation,
            (),
        )

    compatible, compatibility_notices = normalize_for_omml(presentation.body)
    normalized = preprocess_formula_latex(compatible)
    if not normalized:
        return WordFormulaConversion(None, "公式内容为空。", presentation, compatibility_notices)

    style_notices: list[str] = []
    omml, error = latex_to_omml(normalized, style_notices=style_notices)
    notices = tuple(dict.fromkeys((*compatibility_notices, *style_notices)))
    return WordFormulaConversion(omml, error, presentation, notices)


def latex_to_word_omml(
    latex: str,
    *,
    xsl_path: Path,
    warnings: list[str] | None = None,
) -> tuple[Any | None, str]:
    # 保留既有调用签名；公式核心自行解析当前独立工具包内的同版 XSL。
    del xsl_path
    conversion = convert_latex_to_word_formula(latex)
    presentation = conversion.presentation
    if conversion.omml is not None and presentation is not None:
        if presentation.tag is not None or presentation.labels:
            return None, "Word 编辑写入暂不支持公式编号或标签；请用 Markdown 转 Word 完整生成。"
        if warnings is not None:
            warnings.extend(f"公式兼容转换提示：{notice}" for notice in conversion.notices)
    return conversion.omml, conversion.error
