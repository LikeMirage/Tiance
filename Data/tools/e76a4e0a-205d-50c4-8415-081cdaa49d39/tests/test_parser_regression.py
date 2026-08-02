from __future__ import annotations

import markdown_preprocessor
import markdown_tables
from markdown_blocks import collect_blockquote
from markdown_inline import parse_image_token, parse_link_token, tokenize_inline


def test_table_parser_keeps_pipes_inside_code_and_math() -> None:
    cells = markdown_tables.parse_table_row(r"| `$a\mid b$` | $a\mid b$ | a\|b |")

    assert cells == [r"`$a\mid b$`", r"$a\mid b$", "a|b"]


def test_table_parser_keeps_pipes_inside_parenthesized_math() -> None:
    cells = markdown_tables.parse_table_row(r"| key | \(|x|\) | \[a|b\] |")

    assert cells == ["key", r"\(|x|\)", r"\[a|b\]"]


def test_unclosed_inline_syntax_does_not_consume_remaining_table_columns() -> None:
    assert markdown_tables.parse_table_row("| price $5 | status |") == [
        "price $5",
        "status",
    ]
    assert markdown_tables.parse_table_row("| `unfinished | status |") == [
        "`unfinished",
        "status",
    ]


def test_inline_tokenizer_respects_markdown_escapes() -> None:
    tokens = list(tokenize_inline(r"\*literal\* and **bold** and \![alt](image.png)"))

    assert [(token.kind, token.raw) for token in tokens] == [
        ("plain", r"\*literal\* and "),
        ("format", "**bold**"),
        ("plain", r" and \![alt](image.png)"),
    ]


def test_inline_tokenizer_keeps_parentheses_in_link_destinations() -> None:
    text = '[文档](docs/chapter(2).md "第二章") ![图](images/plot(1).png "结果")'
    tokens = list(tokenize_inline(text))

    assert [(token.kind, token.raw) for token in tokens] == [
        ("format", '[文档](docs/chapter(2).md "第二章")'),
        ("plain", " "),
        ("format", '![图](images/plot(1).png "结果")'),
    ]
    assert parse_link_token(tokens[0].raw) == ("文档", "docs/chapter(2).md")
    assert parse_image_token(tokens[2].raw) == ("图", "images/plot(1).png")


def test_preprocessing_does_not_touch_code_block_comments_or_note_syntax() -> None:
    prepared, footnotes, endnotes = markdown_preprocessor.prepare_markdown_content(
        """```html
<!-- KEEP -->
[^code]: KEEP
```

正文[^real]。
<!-- REMOVE -->
[^real]: 真实脚注。
[^end:last]: 真实尾注。
"""
    )

    assert "<!-- KEEP -->" in prepared
    assert "[^code]: KEEP" in prepared
    assert "<!-- REMOVE -->" not in prepared
    assert footnotes == {"real": "真实脚注。"}
    assert endnotes == {"last": "真实尾注。"}


def test_tilde_fence_gets_the_same_preprocessing_protection() -> None:
    prepared, footnotes, _ = markdown_preprocessor.prepare_markdown_content(
        """~~~markdown
<!-- KEEP -->
[^inside]: KEEP
~~~

正文[^outside]。
[^outside]: 外部脚注。
"""
    )

    assert "<!-- KEEP -->" in prepared
    assert "[^inside]: KEEP" in prepared
    assert footnotes == {"outside": "外部脚注。"}


def test_blockquote_soft_lines_form_paragraphs_and_keep_hard_breaks() -> None:
    paragraphs, end_index = collect_blockquote(
        ["> 第一行", "> 第二行  ", "> 第三行", ">", "> 新段", "正文"],
        0,
    )

    assert paragraphs == ["第一行 第二行\n第三行", "新段"]
    assert end_index == 4
