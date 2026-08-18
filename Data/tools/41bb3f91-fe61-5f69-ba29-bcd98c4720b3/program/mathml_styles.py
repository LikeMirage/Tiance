from __future__ import annotations

from typing import Any

from latex_extensions import normalize_word_color


def normalize_mathml_styles(root: Any) -> tuple[str, ...]:
    """Normalizes MathML foreground/background colors before the OMML transform."""
    unsupported: list[str] = []
    for element in root.iter():
        style = element.attrib.get("style", "")
        for declaration in style.split(";"):
            name, separator, value = declaration.partition(":")
            if not separator:
                continue
            attribute = {
                "background": "mathbackground",
                "background-color": "mathbackground",
                "color": "mathcolor",
            }.get(name.strip().lower())
            if attribute:
                _set_mathml_color(element, attribute, value, unsupported)
        for attribute in ("mathcolor", "mathbackground", "color"):
            if attribute in element.attrib:
                _set_mathml_color(element, attribute, element.attrib[attribute], unsupported)
    return tuple(dict.fromkeys(unsupported))


def _set_mathml_color(
    element: Any,
    attribute: str,
    value: str,
    unsupported: list[str],
) -> None:
    color = normalize_word_color(value)
    if color is None:
        unsupported.append(value.strip())
        element.attrib.pop(attribute, None)
        return
    element.set(attribute, color)
