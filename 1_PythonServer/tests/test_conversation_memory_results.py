import pytest

from app.services.project.conversation_memory_results import (
    parse_compaction_result,
)


def test_parse_compaction_result_keeps_canonical_contract():
    result = parse_compaction_result(
        """
        {
          "items": [
            {
              "content": "[用户目标与偏好] 用户要求保持工具系统职责边界。",
              "keywords": ["工具系统", "职责边界"]
            }
          ],
          "handoff": "继续按既有边界实现当前工具。"
        }
        """
    )

    assert result == {
        "items": [
            {
                "content": "[用户目标与偏好] 用户要求保持工具系统职责边界。",
                "keywords": ["工具系统", "职责边界"],
            }
        ],
        "handoff": "继续按既有边界实现当前工具。",
    }


@pytest.mark.parametrize(
    "content",
    [
        '{"items":[{"content":"内容","keywords":[]}]}',
        (
            '{"title":"摘要","items":[{"content":"内容","keywords":[]}],'
            '"handoff":"交接"}'
        ),
        (
            '{"items":[{"source":"1-2","content":"内容","keywords":[]}],'
            '"handoff":"交接"}'
        ),
        (
            '{"items":[{"content":"内容","keywords":"关键词"}],'
            '"handoff":"交接"}'
        ),
    ],
)
def test_parse_compaction_result_rejects_contract_drift(content):
    with pytest.raises(ValueError):
        parse_compaction_result(content)


def test_parse_compaction_result_does_not_truncate_content():
    long_item_content = "A" * 6000
    long_handoff = "B" * 1200
    keywords = [f"keyword-{index}" for index in range(20)]
    content = (
        '{"items":[{"content":"__ITEM__","keywords":__KEYWORDS__}],'
        '"handoff":"__HANDOFF__"}'
    ).replace("__ITEM__", long_item_content).replace(
        "__HANDOFF__",
        long_handoff,
    ).replace("__KEYWORDS__", str(keywords).replace("'", '"'))

    result = parse_compaction_result(content)

    assert result["items"][0]["content"] == long_item_content
    assert result["items"][0]["keywords"] == keywords
    assert result["handoff"] == long_handoff
