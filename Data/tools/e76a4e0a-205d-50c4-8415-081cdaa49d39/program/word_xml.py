from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _qualified_order(*local_names: str) -> tuple[str, ...]:
    return tuple(qn(f"w:{name}") for name in local_names)


CHILD_ORDERS = {
    qn("w:numbering"): _qualified_order(
        "numPicBullet",
        "abstractNum",
        "num",
        "numIdMacAtCleanup",
    ),
    qn("w:abstractNum"): _qualified_order(
        "nsid",
        "multiLevelType",
        "tmpl",
        "name",
        "styleLink",
        "numStyleLink",
        "lvl",
    ),
    qn("w:lvl"): _qualified_order(
        "start",
        "numFmt",
        "lvlRestart",
        "pStyle",
        "isLgl",
        "suff",
        "lvlText",
        "lvlPicBulletId",
        "legacy",
        "lvlJc",
        "pPr",
        "rPr",
    ),
    qn("w:num"): _qualified_order("abstractNumId", "lvlOverride"),
    qn("w:numPr"): _qualified_order("ilvl", "numId", "numberingChange", "ins"),
    qn("w:pPr"): _qualified_order(
        "pStyle",
        "keepNext",
        "keepLines",
        "pageBreakBefore",
        "framePr",
        "widowControl",
        "numPr",
        "suppressLineNumbers",
        "pBdr",
        "shd",
        "tabs",
        "suppressAutoHyphens",
        "kinsoku",
        "wordWrap",
        "overflowPunct",
        "topLinePunct",
        "autoSpaceDE",
        "autoSpaceDN",
        "bidi",
        "adjustRightInd",
        "snapToGrid",
        "spacing",
        "ind",
        "contextualSpacing",
        "mirrorIndents",
        "suppressOverlap",
        "jc",
        "textDirection",
        "textAlignment",
        "textboxTightWrap",
        "outlineLvl",
        "divId",
        "cnfStyle",
        "rPr",
        "sectPr",
        "pPrChange",
    ),
    qn("w:rPr"): _qualified_order(
        "rStyle",
        "rFonts",
        "b",
        "bCs",
        "i",
        "iCs",
        "caps",
        "smallCaps",
        "strike",
        "dstrike",
        "outline",
        "shadow",
        "emboss",
        "imprint",
        "noProof",
        "snapToGrid",
        "vanish",
        "webHidden",
        "color",
        "spacing",
        "w",
        "kern",
        "position",
        "sz",
        "szCs",
        "highlight",
        "u",
        "effect",
        "bdr",
        "shd",
        "fitText",
        "vertAlign",
        "rtl",
        "cs",
        "em",
        "lang",
        "eastAsianLayout",
        "specVanish",
        "oMath",
        "rPrChange",
    ),
    qn("w:tblPr"): _qualified_order(
        "tblStyle",
        "tblpPr",
        "tblOverlap",
        "bidiVisual",
        "tblStyleRowBandSize",
        "tblStyleColBandSize",
        "tblW",
        "jc",
        "tblCellSpacing",
        "tblInd",
        "tblBorders",
        "shd",
        "tblLayout",
        "tblCellMar",
        "tblLook",
        "tblCaption",
        "tblDescription",
        "tblPrChange",
    ),
    qn("w:tcPr"): _qualified_order(
        "cnfStyle",
        "tcW",
        "gridSpan",
        "hMerge",
        "vMerge",
        "tcBorders",
        "shd",
        "noWrap",
        "tcMar",
        "textDirection",
        "tcFitText",
        "vAlign",
        "hideMark",
        "headers",
        "cellIns",
        "cellDel",
        "cellMerge",
        "tcPrChange",
    ),
    qn("w:settings"): _qualified_order(
        "writeProtection",
        "view",
        "zoom",
        "removePersonalInformation",
        "removeDateAndTime",
        "doNotDisplayPageBoundaries",
        "displayBackgroundShape",
        "printPostScriptOverText",
        "printFractionalCharacterWidth",
        "printFormsData",
        "embedTrueTypeFonts",
        "embedSystemFonts",
        "saveSubsetFonts",
        "saveFormsData",
        "mirrorMargins",
        "alignBordersAndEdges",
        "bordersDoNotSurroundHeader",
        "bordersDoNotSurroundFooter",
        "gutterAtTop",
        "hideSpellingErrors",
        "hideGrammaticalErrors",
        "activeWritingStyle",
        "proofState",
        "formsDesign",
        "attachedTemplate",
        "linkStyles",
        "stylePaneFormatFilter",
        "stylePaneSortMethod",
        "documentType",
        "mailMerge",
        "revisionView",
        "trackRevisions",
        "doNotTrackMoves",
        "doNotTrackFormatting",
        "documentProtection",
        "autoFormatOverride",
        "styleLockTheme",
        "styleLockQFSet",
        "defaultTabStop",
        "autoHyphenation",
        "consecutiveHyphenLimit",
        "hyphenationZone",
        "doNotHyphenateCaps",
        "showEnvelope",
        "summaryLength",
        "clickAndTypeStyle",
        "defaultTableStyle",
        "evenAndOddHeaders",
        "bookFoldRevPrinting",
        "bookFoldPrinting",
        "bookFoldPrintingSheets",
        "drawingGridHorizontalSpacing",
        "drawingGridVerticalSpacing",
        "displayHorizontalDrawingGridEvery",
        "displayVerticalDrawingGridEvery",
        "doNotUseMarginsForDrawingGridOrigin",
        "drawingGridHorizontalOrigin",
        "drawingGridVerticalOrigin",
        "doNotShadeFormData",
        "noPunctuationKerning",
        "characterSpacingControl",
        "printTwoOnOne",
        "strictFirstAndLastChars",
        "noLineBreaksAfter",
        "noLineBreaksBefore",
        "savePreviewPicture",
        "doNotValidateAgainstSchema",
        "saveInvalidXml",
        "ignoreMixedContent",
        "alwaysShowPlaceholderText",
        "doNotDemarcateInvalidXml",
        "saveXmlDataOnly",
        "useXSLTWhenSaving",
        "saveThroughXslt",
        "showXMLTags",
        "alwaysMergeEmptyNamespace",
        "updateFields",
        "hdrShapeDefaults",
        "footnotePr",
        "endnotePr",
        "compat",
        "docVars",
        "rsids",
        "mathPr",
        "uiCompat97To2003",
        "attachedSchema",
        "themeFontLang",
        "clrSchemeMapping",
        "doNotIncludeSubdocsInStats",
        "doNotAutoCompressPictures",
        "forceUpgrade",
        "captions",
        "readModeInkLockDown",
        "smartTagType",
        "schemaLibrary",
        "shapeDefaults",
        "doNotEmbedSmartTags",
        "decimalSymbol",
        "listSeparator",
        "chartTrackingRefBased",
        "docId",
        "discardImageEditingData",
        "defaultImageDpi",
        "conflictMode",
    ),
}


def get_or_add_ordered_child(parent: Any, tag: str) -> Any:
    qualified_tag = qn(tag)
    existing = parent.find(qualified_tag)
    if existing is not None:
        return existing
    child = OxmlElement(tag)
    insert_ordered_child(parent, child)
    return child


def insert_ordered_child(parent: Any, child: Any) -> None:
    order = CHILD_ORDERS.get(parent.tag)
    if order is None or child.tag not in order:
        parent.append(child)
        return
    ranks = {tag: index for index, tag in enumerate(order)}
    child_rank = ranks[child.tag]
    for index, current in enumerate(parent):
        current_rank = ranks.get(current.tag)
        if current_rank is not None and current_rank > child_rank:
            parent.insert(index, child)
            return
    parent.append(child)


def find_wordprocessingml_order_error(root: Any) -> str:
    for parent in root.iter():
        order = CHILD_ORDERS.get(parent.tag)
        if order is None:
            continue
        ranks = {tag: index for index, tag in enumerate(order)}
        previous_rank = -1
        previous_name = ""
        for child in parent:
            rank = ranks.get(child.tag)
            if rank is None:
                continue
            current_name = etree.QName(child).localname
            if rank < previous_rank:
                parent_name = etree.QName(parent).localname
                return (
                    f"w:{parent_name} 子节点顺序错误："
                    f"w:{current_name} 不能位于 w:{previous_name} 之后"
                )
            previous_rank = rank
            previous_name = current_name
    return ""
