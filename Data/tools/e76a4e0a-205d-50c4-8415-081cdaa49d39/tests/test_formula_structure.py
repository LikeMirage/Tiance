from __future__ import annotations

from lxml import etree

from formula_converter import _load_xslt, latex_to_omml, preprocess_latex, validate_latex
from omml_validation import OMML_NS, find_omml_structure_error


NS = {"m": OMML_NS}


def test_fraction_with_nary_numerator_keeps_denominator_at_fraction_level() -> None:
    omml, error = latex_to_omml(
        r"\frac{\sum_{i=1}^{n}x_i^2}{1+\sqrt{1+\theta^2}}"
    )

    assert error == ""
    assert omml is not None
    assert find_omml_structure_error(omml) == ""
    fraction = omml.xpath(".//m:f", namespaces=NS)[0]
    assert len(fraction.xpath("./m:num", namespaces=NS)) == 1
    assert len(fraction.xpath("./m:den", namespaces=NS)) == 1
    assert fraction.xpath("./m:num/m:nary/m:e/m:sSubSup", namespaces=NS)
    assert not fraction.xpath(".//m:nary/m:e/m:den", namespaces=NS)


def test_omml_validator_rejects_fraction_without_direct_denominator() -> None:
    fraction = etree.fromstring(
        f'<m:f xmlns:m="{OMML_NS}"><m:num><m:e><m:den/></m:e></m:num></m:f>'
    )

    assert find_omml_structure_error(fraction) == "m:f 必须包含一个直接子节点 m:den"


def test_formula_preprocessing_preserves_punctuation_and_rejects_silent_metadata_loss() -> None:
    assert preprocess_latex("x=1.") == "x=1."
    assert preprocess_latex("x=1，") == "x=1，"
    assert "保留原公式" in validate_latex(r"x=1\tag{A}\label{eq:a}")


def test_formula_symbol_fixes_keep_mathematical_codepoints() -> None:
    assert preprocess_latex(r"\star\cdot\bullet") == "⋆⋅∙"


def test_xslt_transform_is_cached_across_formulas() -> None:
    _load_xslt.cache_clear()

    assert latex_to_omml("x+1")[0] is not None
    assert latex_to_omml("y+2")[0] is not None

    assert _load_xslt.cache_info().misses == 1
    assert _load_xslt.cache_info().hits >= 1
