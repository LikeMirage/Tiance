"""Exercise the shipped Python entry points and real SDK/HTTP authorization offline."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import uvicorn

from app.api.routes.llm import provider_capabilities as routes
from app.domain.llm.provider_catalog import (
    AuthScheme, ModelDiscoveryStrategy, ProviderCatalogEntry, ProviderEndpointTemplate, ProviderProtocolFamily,
)
from app.domain.tools.host_capabilities import declared_host_capabilities, declared_provider_endpoints, declared_session_model_endpoints
from app.services.llm import tool_provider_requests as service
from app.services.tools.host_capability_access import HostCapabilityAccessService
from app.services.tools.tool_execution_runtime import build_python_command, build_tool_python_paths
from tests.formal_tool_paths import resolve_formal_tool_root


def test_packaged_search_tools_through_host_and_scoped_credentials(tmp_path, monkeypatch):
    access = HostCapabilityAccessService()
    monkeypatch.setattr(routes, "get_host_capability_access_service", lambda: access)
    urls = {"custom": "https://example.test/tenant/go/v1/chat/completions", "deepseek": "https://api.deepseek.com/chat/completions"}
    def provider(provider_id):
        url = urls[provider_id]
        return (ProviderCatalogEntry(
            provider_id=provider_id, display_name="Test", profile_id="generic",
            protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE,
            generation_auth_schemes={ProviderProtocolFamily.OPENAI_COMPATIBLE: AuthScheme.X_API_KEY},
            model_discovery_strategy=ModelDiscoveryStrategy.OPENAI_MODELS,
            model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN, endpoints=ProviderEndpointTemplate(url, url, None),
        ), SimpleNamespace(api_base_url=url))
    monkeypatch.setattr(service, "_provider", provider)
    monkeypatch.setattr(service, "_key", lambda entry, config, required: entry.provider_id+"-credential")
    monkeypatch.setattr(service, "resolve_provider_profile", lambda *args: SimpleNamespace(include_responses_web_search_sources=False))
    monkeypatch.setattr(service, "resolve_request_headers", lambda *args, **kwargs: {})
    sent = []
    def respond(request):
        sent.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        if request.url.path.endswith("/responses"):
            return httpx.Response(200, json={"output":[{"type":"web_search_call","action":{"query":"test"}},
                {"type":"message","content":[{"type":"output_text","text":"found"}]}]})
        if request.url.path.endswith("/fetch"):
            return httpx.Response(200,json={"title":"fixture","content":"page text"})
        return httpx.Response(200,json={"results":[]})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(service, "get_shared_http_client", lambda: upstream)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        thread = Thread(target=server.run, kwargs={"sockets":[sock]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic()+5
            while not server.started:
                assert thread.is_alive() and monotonic() < deadline
                sleep(0.01)
            def execute(name, payload, provider_id="custom", model_id="bound-model"):
                root = resolve_formal_tool_root(name)
                runtime = json.loads((root/".tool/tool.json").read_text(encoding="utf-8"))["runtime"]
                grant = access.issue_grant(tool_name=name, tool_call_id="call", session_id="background",
                    model_id=model_id, provider_id=provider_id, project_id="project", lifetime_seconds=60,
                    capabilities=declared_host_capabilities(runtime), provider_endpoints=declared_provider_endpoints(runtime),
                    session_model_endpoints=declared_session_model_endpoints(runtime))
                local = tmp_path/name
                if not local.exists():
                    shutil.copytree(root/".tool", local/".tool")
                    shutil.copytree(root/"program", local/"program", ignore=shutil.ignore_patterns("config.json","__pycache__"))
                entry = local/runtime["entry"]
                paths = build_tool_python_paths(entry_path=entry, tool_root=local, backend_site_packages_path=tmp_path)
                command = build_python_command(python_executable=Path(sys.executable), entry_path=entry, python_paths=paths)
                env = {**os.environ, "PYTHONUTF8":"1", "TIANCE_HOST_CAPABILITY_TOKEN":grant.token,
                       "TIANCE_API_BASE_URL":f"http://127.0.0.1:{port}/api", "TIANCE_WORKSPACE_ROOT":str(tmp_path)}
                try:
                    run = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                                         encoding="utf-8", timeout=15, cwd=tmp_path, env=env)
                finally:
                    access.revoke(grant.token)
                assert run.returncode == 0, run.stdout + run.stderr
                result = json.loads(run.stdout)
                assert result["ok"] and "-credential" not in run.stdout
                return result["data"]

            assert execute("network_search", {"query":"test"})["answer"] == "found"
            assert execute("network_search", {"query":"test"}, "deepseek", "deepseek-flash")["answer"] == "found"
            assert execute("deepseek_official_web_search", {"query":"test"})["result_count"] == 0
            assert execute("deepseek_official_web_search", {"action":"fetch","url":"https://example.org"})["page"]["content"] == "page text"
            assert [item[:2] for item in sent] == [
                ("https://example.test/tenant/go/v1/responses", "Bearer custom-credential"),
                ("https://api.deepseek.com/v1/responses", "Bearer deepseek-credential"),
                ("https://api.deepseek.com/v1/tools/search", "Bearer deepseek-credential"),
                ("https://api.deepseek.com/v1/tools/fetch", "Bearer deepseek-credential"),
            ]
            assert sent[0][2]["model"] == "bound-model" and sent[0][2]["tools"] == [{"type":"web_search"}]
            assert sent[1][2]["model"] == "deepseek-flash" and sent[1][2]["tools"] == [{"type":"deepseek_web_search"}]
            assert "model" not in sent[2][2]
        finally:
            server.should_exit = True
            thread.join(6)
            asyncio.run(upstream.aclose())
