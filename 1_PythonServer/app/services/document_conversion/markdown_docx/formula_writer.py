from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from docx.shared import Pt

from . import browser_renderer
from . import word_formatting as formatting
from .formula_converter import latex_to_omml, preprocess_latex, validate_latex
from .latex_extensions import needs_image_rendering, normalize_for_image, normalize_for_omml
from .word_formatting import FontSettings
from .warning_collector import WarningCollector


class FormulaWriter:
    """Converts one LaTeX fragment into editable OMML, an image, or readable source."""

    def __init__(
        self,
        document,
        fonts: FontSettings,
        warnings: WarningCollector,
        render_budget: browser_renderer.BrowserRenderBudget,
    ) -> None:
        self._document = document
        self._fonts = fonts
        self._warnings = warnings
        self._render_budget = render_budget

    def write(
        self,
        paragraph,
        latex: str,
        *,
        font_size=None,
        display_mode: bool = False,
        max_width=None,
    ) -> None:
        original = latex.strip()
        if not original:
            return
        validation_error = validate_latex(original)
        if validation_error:
            self._write_degraded(paragraph, original, validation_error, font_size=font_size)
            return
        if needs_image_rendering(original):
            self._write_image(
                paragraph,
                original,
                display_mode=display_mode,
                max_width=max_width,
                font_size=font_size,
            )
            return
        compatible, notices = normalize_for_omml(original)
        normalized = preprocess_latex(compatible)
        if not normalized:
            return
        style_notices: list[str] = []
        omml, error = latex_to_omml(normalized, style_notices=style_notices)
        if omml is None:
            self._write_degraded(paragraph, original, error, font_size=font_size)
            return
        formatting.apply_omml_font(omml, self._fonts, size=font_size)
        paragraph._p.append(omml)
        self._warnings.extend(f"公式兼容转换提示：{notice}" for notice in notices)
        self._warnings.extend(f"公式兼容转换提示：{notice}" for notice in style_notices)

    def _write_image(
        self,
        paragraph,
        latex: str,
        *,
        display_mode: bool,
        max_width,
        font_size,
    ) -> None:
        try:
            normalized, notices = normalize_for_image(latex)
            with TemporaryDirectory(prefix="md2docx-formula-") as temp_dir:
                image_path = Path(temp_dir) / "formula.png"
                browser_renderer.render_katex_png(
                    normalized,
                    image_path,
                    display_mode=display_mode,
                    budget=self._render_budget,
                )
                paragraph.add_run().add_picture(
                    str(image_path),
                    width=formatting.formula_image_render_width(
                        image_path,
                        max_width or formatting.block_image_max_width(self._document),
                    ),
                )
            detail = f"；{'；'.join(notices)}" if notices else ""
            self._warnings.append(f"扩展公式已作为图片插入（不可编辑）：{latex}{detail}")
        except Exception as exc:
            self._write_degraded(
                paragraph,
                latex,
                f"扩展公式图片渲染失败：{exc}",
                font_size=font_size,
            )

    def _write_degraded(self, paragraph, latex: str, error: str, *, font_size=None) -> None:
        self._warnings.append(f"公式降级为文本：{latex}，原因：{error}")
        run = paragraph.add_run(latex)
        formatting.apply_math_run_font(run, self._fonts)
        run.font.size = font_size or Pt(10)
