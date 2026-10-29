from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.static_frontend import FrontendStaticFiles


@pytest.fixture
def client(tmp_path):
    (tmp_path / "assets").mkdir()
    for name in ("index.html", "favicon.svg", "startup-background.png", "assets/plain.js",
                 "assets/index-AbCd1234.js", "assets/index-ZyxW5678.css", "assets/font-AB_c-123.woff2"):
        (tmp_path / name).write_text("test", encoding="utf-8")
    app = FastAPI()
    app.mount("/app", FrontendStaticFiles(directory=str(tmp_path), html=True))
    with TestClient(app) as result:
        yield result


@pytest.mark.parametrize("path", ["/app/", "/app/index.html", "/app/favicon.svg",
                                  "/app/startup-background.png", "/app/assets/plain.js"])
def test_entry_and_unversioned_files_are_not_frozen(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("name", ["index-AbCd1234.js", "index-ZyxW5678.css", "font-AB_c-123.woff2"])
def test_versioned_assets_allow_reuse_including_head_and_conditional_requests(client, name):
    path = f"/app/assets/{name}"
    first = client.get(path)
    assert first.status_code == 200
    for response in (first, client.head(path), client.get(path, headers={"If-None-Match": first.headers["etag"]})):
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "pragma" not in response.headers
        assert "expires" not in response.headers
    assert client.get(path, headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    assert client.get("/app/assets/missing-ABCDEFGH.js").status_code == 404
