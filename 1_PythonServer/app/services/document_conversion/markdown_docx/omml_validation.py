from __future__ import annotations

from typing import Any

from lxml import etree


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

REQUIRED_CHILDREN = {
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

REQUIRED_PARENTS = {
    "deg": {"rad"},
    "den": {"f"},
    "fName": {"func"},
    "lim": {"limLow", "limUpp"},
    "mr": {"m"},
    "num": {"f"},
    "sub": {"nary", "sPre", "sSub", "sSubSup"},
    "sup": {"nary", "sPre", "sSubSup", "sSup"},
}


def find_omml_structure_error(root: Any) -> str:
    """Returns the first critical OMML content-model violation, if any."""
    for element in root.iter():
        name = _omml_local_name(element)
        if name is None:
            continue
        parent_names = REQUIRED_PARENTS.get(name)
        if parent_names is not None:
            parent_name = _omml_local_name(element.getparent())
            if parent_name not in parent_names:
                return f"m:{name} 不能位于 m:{parent_name or 'unknown'} 下"

        required = REQUIRED_CHILDREN.get(name)
        if required is None:
            continue
        child_names = [
            child_name
            for child in element
            if (child_name := _omml_local_name(child)) is not None
        ]
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
    if qualified.namespace != OMML_NS:
        return None
    return qualified.localname
