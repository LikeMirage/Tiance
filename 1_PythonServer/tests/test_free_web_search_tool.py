from __future__ import annotations

import importlib.util
import gzip
from json import dumps, loads
from pathlib import Path
import socket
import sys

import pytest

from tests.formal_tool_paths import resolve_formal_tool_root


TOOL_ROOT = resolve_formal_tool_root("free_web_search")
PROGRAM_ROOT = TOOL_ROOT / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

from bing_search import BingResultsParser, _normalize_results
from additional_search_engines import DuckDuckGoParser, SogouParser, unwrap_duckduckgo_url
from http_client import _decompress_body
from url_safety import UnsafeUrlError, normalize_public_url, unwrap_bing_redirect, validate_public_url
from webpage_reader import MainTextExtractor, PageReadResult, _client_redirect_target


def _load_main_module():
    spec = importlib.util.spec_from_file_location("free_web_search_main", PROGRAM_ROOT / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(relative_path: str):
    return loads((TOOL_ROOT / relative_path).read_text(encoding="utf-8"))


def test_free_web_search_contract_supports_batch_queries_and_urls():
    manifest = _read_json(".tool/tool.json")
    input_schema = _read_json(".tool/input.schema.json")

    assert manifest["name"] == "free_web_search"
    assert manifest["runtime"]["type"] == "python"
    assert manifest["loading"]["dynamic"] is True
    assert manifest["execution"]["parallel"] is False
    assert set(input_schema["properties"]) == {
        "engine",
        "queries",
        "urls",
        "mode",
        "max_results_per_query",
    }
    assert input_schema["properties"]["mode"]["default"] == "search"
    assert input_schema["properties"]["mode"]["enum"] == ["search", "content"]
    assert input_schema["properties"]["engine"]["default"] == "baidu"
    assert input_schema["properties"]["engine"]["enum"] == ["baidu", "bing", "duckduckgo", "sogou"]


def test_bing_parser_keeps_organic_and_news_but_not_advertising():
    html = """
    <main id="b_content"><ol id="b_results">
      <li class="b_ad"><h2><a href="https://ads.example/">Advertisement</a></h2><p>Ad text</p></li>
      <li class="b_algo"><h2><a href="https://example.com/article?utm_source=bing">Useful result</a></h2>
        <div class="b_caption"><p>Useful summary.</p></div></li>
      <div class="b_nwsAns"><h2><a href="https://news.example/story">News result</a></h2>
        <p>News summary.</p></div>
    </ol></main>
    """
    parser = BingResultsParser()
    parser.feed(html)
    parser.close()
    normalized = _normalize_results(parser.results, set())

    assert [item["title"] for item in normalized] == ["Useful result", "News result"]
    assert normalized[0]["url"] == "https://example.com/article"
    assert normalized[1]["result_type"] == "news"


def test_bing_redirect_and_url_normalization_are_deterministic():
    encoded = "a1aHR0cHM6Ly9leGFtcGxlLmNvbS9kb2M_dXRtX3NvdXJjZT1iaW5n"
    unwrapped = unwrap_bing_redirect(f"https://www.bing.com/ck/a?u={encoded}")

    assert unwrapped == "https://example.com/doc?utm_source=bing"
    assert normalize_public_url(unwrapped) == "https://example.com/doc"


def test_duckduckgo_parser_unwraps_redirect_and_extracts_snippet():
    html = """
    <div class="result results_links_deep web-result">
      <h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">Useful result</a></h2>
      <a class="result__snippet" href="#">Useful summary.</a>
    </div>
    """
    parser = DuckDuckGoParser()
    parser.feed(html)
    parser.close()

    assert parser.results == [
        {"title": "Useful result", "url": "https://example.com/doc", "snippet": "Useful summary."}
    ]
    assert unwrap_duckduckgo_url("https://example.com/direct") == "https://example.com/direct"


def test_sogou_parser_extracts_relative_result_links():
    html = """
    <div class="vrwrap">
      <h3 class="vr-title"><a href="/link?url=abc">搜狗结果</a></h3>
      <div class="fz-mid">结果摘要。</div>
    </div>
    """
    parser = SogouParser()
    parser.feed(html)
    parser.close()

    assert parser.results == [
        {"title": "搜狗结果", "url": "https://www.sogou.com/link?url=abc", "snippet": "结果摘要。"}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/private",
        "http://localhost/private",
        "http://10.0.0.1/private",
        "http://198.18.0.1/proxy-mapping-must-not-be-literal",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "https://user:password@example.com/private",
    ],
)
def test_private_or_credentialed_urls_are_rejected(url: str):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url, resolve_dns=False)


def test_proxy_mapped_public_dns_is_allowed_but_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.1.10", 443))],
    )
    assert validate_public_url("https://example.com") == "https://example.com/"

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))],
    )
    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://example.com")


def test_main_text_extractor_prefers_article_and_removes_noise():
    html = """
    <html><head><title>Example title</title><script>secret()</script></head>
    <body><nav>Navigation noise</nav><article><h1>Article heading</h1>
    <p>This is the useful paragraph with enough content to remain in the extracted document.</p>
    <p>This second paragraph makes the article clearly longer than the minimum useful threshold.</p>
    </article><footer>Footer noise</footer></body></html>
    """
    parser = MainTextExtractor()
    parser.feed(html)
    parser.close()
    content, method = parser.extracted_content()

    assert parser.title() == "Example title"
    assert method == "main-content"
    assert "Article heading" in content
    assert "useful paragraph" in content
    assert "Navigation noise" not in content
    assert "Footer noise" not in content
    assert "secret()" not in content


def test_http_client_decompresses_gzip_with_output_limit():
    body = ("useful text " * 100).encode("utf-8")
    decoded, truncated = _decompress_body(gzip.compress(body), "gzip", max_bytes=100)

    assert decoded == body[:100]
    assert truncated is True


def test_client_redirect_target_supports_sogou_style_script_and_rejects_plain_page():
    html = '<meta name="referrer"><script>window.location.replace("https://example.com/page")</script>'

    assert _client_redirect_target(html, "https://www.sogou.com/link?id=1") == "https://example.com/page"
    assert _client_redirect_target("<html><body>ordinary page</body></html>", "https://example.com") == ""


def test_batch_run_writes_workspace_files_without_returning_body(monkeypatch, tmp_path: Path):
    module = _load_main_module()
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        module,
        "search_web",
        lambda engine, query, max_results: [
            {
                "rank": 1,
                "title": f"Result for {query}",
                "url": "https://example.com/article",
                "snippet": "Saved snippet",
                "source": "example.com",
                "result_type": "organic",
            }
        ],
    )
    body = "This exact body is written to disk and must not appear in the tool response. " * 4
    monkeypatch.setattr(module, "read_page", lambda url: _successful_page(url, body))

    result = module.run(
        {
            "queries": ["first query", "second query"],
            "urls": ["https://example.org/direct"],
            "mode": "content",
            "max_results_per_query": 3,
        }
    )

    assert result["ok"] is True
    assert result["data"]["engine"] == "baidu"
    assert result["data"]["query_count"] == 2
    assert result["data"]["direct_url_count"] == 1
    assert result["data"]["saved_count"] == 3
    assert result["data"]["content_character_count"] == len(body) * 3
    response_text = dumps(result, ensure_ascii=False)
    assert "This exact body is written to disk" not in response_text
    index_path = tmp_path / result["data"]["index_file"]
    manifest_path = tmp_path / result["data"]["manifest_file"]
    assert index_path.is_file()
    assert manifest_path.is_file()
    assert "(queries/001-first-query/index.md)" in index_path.read_text(encoding="utf-8")
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    content_paths = [
        item["content_file"]
        for query in manifest["queries"]
        for item in query["results"]
    ]
    content_paths.extend(item["content_file"] for item in manifest["direct_urls"])
    assert all((tmp_path / path).read_text(encoding="utf-8").startswith("This exact body") for path in content_paths)


def test_batch_validation_does_not_silently_truncate():
    module = _load_main_module()
    result = module.run({"queries": [f"query {index}" for index in range(21)]})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "BATCH_TOO_LARGE"


def test_batch_validation_rejects_duplicate_inputs():
    module = _load_main_module()
    result = module.run({"queries": ["same query", " Same Query "]})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "DUPLICATE_ARGUMENT"


def test_batch_validation_rejects_unknown_search_engine():
    module = _load_main_module()
    result = module.run({"queries": ["query"], "engine": "google"})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_ENGINE"


def test_content_batch_validation_rejects_excessive_page_fetches():
    module = _load_main_module()
    result = module.run(
        {
            "queries": ["first", "second", "third"],
            "mode": "content",
            "max_results_per_query": 34,
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "BATCH_TOO_LARGE"
    assert result["error_info"]["details"]["requested_content_pages"] == 102


def _successful_page(url: str, body: str) -> PageReadResult:
    return PageReadResult(
        ok=True,
        requested_url=url,
        final_url=url,
        title="Saved page",
        content_type="text/html",
        status_code=200,
        content=body,
        binary_content=None,
        binary_extension=None,
        byte_count=len(body.encode("utf-8")),
        character_count=len(body),
        truncated=False,
        extraction_method="main-content",
        error_code=None,
        error=None,
        warnings=(),
    )
