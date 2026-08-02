from __future__ import annotations

from excel_errors import ToolError


def formula_value(value: str, location: str) -> str:
    stripped = value.strip()
    formula = stripped if stripped.startswith("=") else f"={stripped}"
    validate_formula_syntax(formula, location)
    return formula


def validate_formula_syntax(formula: str, location: str) -> None:
    in_double_quote = False
    in_single_quote = False
    depth = 0
    index = 0
    while index < len(formula):
        char = formula[index]
        next_char = formula[index + 1] if index + 1 < len(formula) else ""
        if char == '"' and not in_single_quote:
            if in_double_quote and next_char == '"':
                index += 2
                continue
            in_double_quote = not in_double_quote
        elif char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif not in_double_quote and not in_single_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise ToolError(
                        "INVALID_FORMULA",
                        "公式括号不匹配。",
                        {"cell": location, "formula": formula},
                    )
        index += 1

    if in_double_quote or in_single_quote:
        raise ToolError(
            "INVALID_FORMULA",
            "公式引号未闭合。",
            {"cell": location, "formula": formula},
        )
    if depth != 0:
        raise ToolError(
            "INVALID_FORMULA",
            "公式括号未闭合。",
            {"cell": location, "formula": formula, "unclosed_parentheses": depth},
        )
