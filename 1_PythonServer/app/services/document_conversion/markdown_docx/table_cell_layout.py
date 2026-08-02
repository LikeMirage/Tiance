from __future__ import annotations

import re
from dataclasses import dataclass

from . import markdown_inline
from .text_measurement import TextMeasurer, is_east_asian_character


INLINE_IMAGE_WIDTH_POINTS = 108.0
MIN_FORMULA_WIDTH_POINTS = 18.0
FORMULA_WIDTH_SCALE = 0.82
CJK_OPENING_PUNCTUATION = frozenset("（【《「『〔〈“‘")
CJK_CLOSING_PUNCTUATION = frozenset("，。！？；：、）】》」』〕〉”’")
FORMULA_COMMAND_TEXT = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "phi": "φ",
    "omega": "ω",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "infty": "∞",
    "sqrt": "√",
    "leq": "≤",
    "geq": "≥",
    "neq": "≠",
    "times": "×",
    "cdot": "·",
    "pm": "±",
    "rightarrow": "→",
    "leftarrow": "←",
}


@dataclass(frozen=True, slots=True)
class MeasuredToken:
    width: float
    gap_before: float = 0.0


@dataclass(frozen=True, slots=True)
class WrapMeasurement:
    lines: int
    overflow_points: float


@dataclass(frozen=True, slots=True)
class CellLayout:
    lines: tuple[tuple[MeasuredToken, ...], ...]
    minimum_width: float
    preferred_width: float

    def wrap(self, available_width: float) -> WrapMeasurement:
        width = max(1.0, available_width)
        total_lines = 0
        overflow = 0.0
        for line in self.lines:
            if not line:
                total_lines += 1
                continue
            line_count = 1
            used = 0.0
            for token in line:
                gap = token.gap_before if used > 0 else 0.0
                if used > 0 and used + gap + token.width > width:
                    line_count += 1
                    used = token.width
                else:
                    used += gap + token.width
                overflow += max(0.0, token.width - width)
            total_lines += line_count
        return WrapMeasurement(lines=max(1, total_lines), overflow_points=overflow)


def measure_cell(text: str, measurer: TextMeasurer, *, bold: bool = False) -> CellLayout:
    line_tokens: list[list[MeasuredToken]] = [[]]
    for inline_token in markdown_inline.tokenize_inline(text):
        if inline_token.kind == "plain":
            _append_plain(line_tokens, inline_token.value, measurer, bold=bold)
            continue
        _append_inline_token(
            line_tokens,
            inline_token.kind,
            inline_token.raw,
            inline_token.value,
            measurer,
            bold=bold,
        )
    lines = tuple(tuple(line) for line in line_tokens) or ((),)
    token_widths = [token.width for line in lines for token in line]
    preferred = max(
        (
            sum(
                token.width + (token.gap_before if index > 0 else 0.0)
                for index, token in enumerate(line)
            )
            for line in lines
        ),
        default=0.0,
    )
    return CellLayout(
        lines=lines,
        minimum_width=max(token_widths, default=0.0),
        preferred_width=preferred,
    )


def _append_inline_token(
    lines: list[list[MeasuredToken]],
    token_type: str,
    token: str,
    value: str,
    measurer: TextMeasurer,
    *,
    bold: bool,
) -> None:
    if token_type == "code":
        _append_measured_token(lines, measurer.measure(value, role="code", bold=bold))
        return
    if token_type == "math":
        _append_formula(lines, value, measurer)
        return
    if token.startswith("!["):
        _append_measured_token(lines, INLINE_IMAGE_WIDTH_POINTS)
        return
    if token.startswith("[!["):
        _append_plain(lines, token, measurer, bold=bold)
        return
    if token.startswith("[^"):
        _append_measured_token(lines, measurer.measure("1", bold=bold))
        return
    if token.startswith("["):
        match = re.match(r"^\[([^\]\n]+)\]\(.*\)$", token)
        _append_plain(lines, match.group(1) if match else token, measurer, bold=bold)
        return
    if token.startswith(("**", "__")):
        _append_plain(lines, token[2:-2], measurer, bold=True)
        return
    if token.startswith("~~"):
        _append_plain(lines, token[2:-2], measurer, bold=bold)
        return
    if token.startswith(r"\("):
        _append_formula(lines, token[2:-2], measurer)
        return
    if token.startswith("*"):
        _append_plain(lines, token[1:-1], measurer, bold=bold)
        return
    _append_plain(lines, token, measurer, bold=bold)


def _append_plain(
    lines: list[list[MeasuredToken]],
    text: str,
    measurer: TextMeasurer,
    *,
    bold: bool,
) -> None:
    cleaned = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    cleaned = markdown_inline.unescape_markdown(cleaned)
    cleaned = markdown_inline.strip_html_tags(cleaned)
    parts = cleaned.split("\n")
    for index, part in enumerate(parts):
        if index > 0:
            lines.append([])
        lines[-1].extend(_measure_plain_tokens(part, measurer, bold=bold))


def _measure_plain_tokens(
    text: str,
    measurer: TextMeasurer,
    *,
    bold: bool,
) -> list[MeasuredToken]:
    tokens: list[MeasuredToken] = []
    word: list[str] = []
    prefix: list[str] = []
    pending_gap = 0.0

    def flush_word() -> None:
        nonlocal pending_gap
        if not word and not prefix:
            return
        value = "".join(prefix + word)
        tokens.append(
            MeasuredToken(
                width=measurer.measure(value, bold=bold),
                gap_before=pending_gap,
            )
        )
        word.clear()
        prefix.clear()
        pending_gap = 0.0

    for char in text:
        if char.isspace():
            flush_word()
            pending_gap += measurer.measure(char, bold=bold)
            continue
        if char in CJK_OPENING_PUNCTUATION:
            flush_word()
            prefix.append(char)
            continue
        if char in CJK_CLOSING_PUNCTUATION:
            flush_word()
            width = measurer.measure(char, bold=bold)
            if tokens and pending_gap == 0:
                previous = tokens[-1]
                tokens[-1] = MeasuredToken(
                    width=previous.width + width,
                    gap_before=previous.gap_before,
                )
            else:
                tokens.append(MeasuredToken(width=width, gap_before=pending_gap))
                pending_gap = 0.0
            continue
        if is_east_asian_character(char):
            flush_word()
            value = "".join(prefix) + char
            prefix.clear()
            tokens.append(
                MeasuredToken(
                    width=measurer.measure(value, bold=bold),
                    gap_before=pending_gap,
                )
            )
            pending_gap = 0.0
            continue
        word.append(char)
    flush_word()
    return tokens


def _append_formula(
    lines: list[list[MeasuredToken]],
    latex: str,
    measurer: TextMeasurer,
) -> None:
    visible_lines = _formula_visible_lines(latex)
    structural_bonus = len(re.findall(r"\\(?:sum|prod|int|frac|sqrt)\b", latex)) * 2.5
    for line_index, visible_line in enumerate(visible_lines or [""]):
        if line_index:
            lines.append([])
        segments = _formula_break_segments(visible_line)
        bonus_per_segment = structural_bonus / max(1, len(segments))
        for segment in segments:
            width = measurer.measure(segment, role="math") * FORMULA_WIDTH_SCALE
            _append_measured_token(
                lines,
                max(MIN_FORMULA_WIDTH_POINTS, width + bonus_per_segment),
            )


def _append_measured_token(lines: list[list[MeasuredToken]], width: float) -> None:
    lines[-1].append(MeasuredToken(width=max(0.0, width)))


def _formula_visible_lines(latex: str) -> list[str]:
    source = re.sub(r"\\(?:begin|end)\{[^{}]+\}", "", latex)
    rows = re.split(r"\\\\(?:\[[^\]]*\])?", source)
    return [_formula_visible_text(row) for row in rows]


def _formula_visible_text(latex: str) -> str:
    value = re.sub(r"\\(?:left|right)(?=\\|[()[\]{}|.])", "", latex)
    value = re.sub(r"\\(?:quad|qquad|,|;|:|!)", " ", value)
    value = re.sub(
        r"\\([A-Za-z]+)",
        lambda match: FORMULA_COMMAND_TEXT.get(match.group(1), "x"),
        value,
    )
    value = value.replace("&", " ")
    value = re.sub(r"[{}_^]", "", value)
    value = value.replace("\\", "")
    return re.sub(r"\s+", " ", value).strip()


def _formula_break_segments(visible_text: str) -> list[str]:
    if not visible_text:
        return [""]
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[=+\-−≤≥≈≠;,，；])\s*", visible_text)
        if segment.strip()
    ]
    return segments or [visible_text]
