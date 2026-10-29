import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import tiance_runtime
from app.api.routes.tools import host_capabilities as routes
from app.core.errors import register_exception_handlers
from app.core.gateway_auth import GatewayAuthenticationMiddleware
from app.domain.llm.chat import ChatToolCall
from app.domain.tools.host_capabilities import HostCapability, HOST_CAPABILITIES, declared_host_capabilities
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage
from app.services.tools import catalog_access, host_capability_access
from app.services.tools.catalog import ToolCatalogService
from app.services.tools.host_capability_access import HostCapabilityAccessService
from app.services.tools.tool_execution import ToolExecutionService, ToolExecutionContext
from app.services.tools.tool_registry import ToolRegistryService
from tests.test_load_tool_info_tool import _load_tool_info_module
from tests.test_tool_catalog import _create_catalog_tool
from tests.test_tool_execution import _create_tool_root, _FakeRegistry
from tests.tool_project_test_support import ToolProjectFixture
from app.api.routes import github_platform


def issue(access, **overrides):
    values = dict(tool_name='my_custom_tool', tool_project_id='installed-tool-project',
        tool_call_id='call', provider_id='provider', model_id='model',
        project_id='project', session_id='session', run_id='run-1', lifetime_seconds=60,
        capabilities=(HostCapability.TOOL_CATALOG, HostCapability.RUN_STATUS),
        enabled_tool_names=('read_text_file',))
    values.update(overrides)
    return access.issue_grant(**values)


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    access = HostCapabilityAccessService()
    monkeypatch.setattr(routes, 'get_host_capability_access_service', lambda: access)
    fixture = ToolProjectFixture(tmp_path / 'tools')
    _create_catalog_tool(fixture)
    registry = ToolRegistryService(fixture)
    registry.rebuild_registry()
    monkeypatch.setattr(routes, 'get_tool_catalog_service', lambda: ToolCatalogService(registry))
    session_settings = SimpleNamespace(tools_enabled=True, enabled_tool_names=('read_text_file',))
    observed = []
    def get_session(project, session):
        observed.append((project, session))
        return SimpleNamespace(settings=session_settings)
    monkeypatch.setattr(catalog_access, 'get_project_conversation_service',
        lambda: SimpleNamespace(get_session=get_session))
    run = {'running': True, 'run_id': 'run-1'}
    async def get_run_status(project, session):
        assert (project, session) == ('project', 'session')
        return dict(run)
    monkeypatch.setattr(routes, 'get_conversation_run_manager', lambda: SimpleNamespace(get_run_status=get_run_status))
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GatewayAuthenticationMiddleware, token='private-gateway-token')
    app.include_router(routes.router, prefix='/api')
    app.include_router(github_platform.router, prefix='/api')
    monkeypatch.setattr(github_platform, 'get_host_capability_access_service', lambda: access)
    with TestClient(app) as client:
        yield SimpleNamespace(access=access, client=client, settings=session_settings, run=run, observed=observed)


def headers(grant):
    return {'Authorization': 'Bearer ' + grant.token}


@pytest.mark.parametrize('operation', ['get_parameters', 'get_examples'])
def test_real_loader_sdk_gateway_authorization_and_catalog_chain(bridge, monkeypatch, operation):
    grant = issue(bridge.access)
    monkeypatch.setenv('TIANCE_API_BASE_URL', 'http://testserver/api')
    monkeypatch.setenv('TIANCE_HOST_CAPABILITY_TOKEN', grant.token)
    def urlopen(request, timeout):
        response = bridge.client.request(request.method, urlsplit(request.full_url).path,
            headers=dict(request.header_items()), content=request.data)
        if response.is_error:
            raise HTTPError(request.full_url, response.status_code, 'error', {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)
    monkeypatch.setattr(tiance_runtime, 'urlopen', urlopen)
    loader = _load_tool_info_module()
    result = loader.run({'operation': operation, 'tool_name': 'read_text_file'})
    assert result['ok'] is True, result
    if operation == 'get_parameters':
        assert result['data']['input_schema']['required'] == ['file_path']
    else:
        assert result['data']['returned_examples'] > 0
    assert bridge.observed == [('project', 'session')]
    bridge.access.revoke(grant.token)
    assert loader.run({'operation': operation, 'tool_name': 'read_text_file'})['ok'] is False


def test_catalog_rejects_absent_wrong_expired_or_forged_scope_and_obeys_session_selection(bridge, monkeypatch):
    path = '/api/tools/capabilities/catalog'
    body = {'operation': 'get_parameters', 'tool_name': 'read_text_file'}
    assert bridge.client.post(path, json=body).status_code == 401
    other = issue(bridge.access, capabilities=(HostCapability.DEEPSEEK_WEB,))
    assert bridge.client.post(path, json=body, headers=headers(other)).status_code == 401
    grant = issue(bridge.access)
    assert bridge.client.post(path, json={**body, 'session_id': 'foreign'}, headers=headers(grant)).status_code == 422
    denied = issue(bridge.access, enabled_tool_names=())
    assert bridge.client.post(path, json=body, headers=headers(denied)).status_code == 404
    bridge.settings.tools_enabled = False
    assert bridge.client.post(path, json=body, headers=headers(grant)).status_code == 404
    # This capability credential never authenticates ordinary UI endpoints.
    assert bridge.client.get('/api/tools/catalog/summaries', headers=headers(grant)).status_code == 401
    monkeypatch.setattr(host_capability_access, 'monotonic', lambda: grant.expires_at + 1)
    assert bridge.client.post(path, json=body, headers=headers(grant)).status_code == 401


def test_observer_outlives_call_but_cannot_access_other_capabilities_or_a_new_run(bridge):
    parent = issue(bridge.access)
    path = '/api/tools/capabilities/run-status'
    response = bridge.client.post(path, json={'action': 'watch'}, headers=headers(parent))
    assert response.status_code == 200
    token = response.json()['token']
    auth = {'Authorization': 'Bearer ' + token}
    bridge.access.revoke(parent.token)
    assert bridge.client.post(path, json={}, headers=auth).json() == {'running': True, 'run_id': 'run-1'}
    assert bridge.client.post(path, json={'action': 'watch'}, headers=auth).status_code == 400
    assert bridge.client.post('/api/tools/capabilities/catalog', json={'operation': 'get_parameters', 'tool_name': 'read_text_file'}, headers=auth).status_code == 401
    bridge.run['run_id'] = 'run-2'
    assert bridge.client.post(path, json={}, headers=auth).json() == {'running': False, 'run_id': None}
    assert bridge.client.post(path, json={}, headers=auth).status_code == 401


def test_observer_expires_without_heartbeat_and_cannot_be_revived(bridge, monkeypatch):
    parent = issue(bridge.access)
    observer = bridge.access.delegate_run_observer(parent)
    monkeypatch.setattr(host_capability_access, 'monotonic', lambda: observer.expires_at + 1)
    assert not bridge.access.renew_run_observer(observer.token)
    assert bridge.client.post('/api/tools/capabilities/run-status', json={}, headers=headers(observer)).status_code == 401


@pytest.mark.parametrize('name', ['my_search', 'renamed_copy', 'network_search'])
def test_execution_uses_declaration_not_tool_name_and_revokes_all_capabilities(tmp_path, name):
    root = _create_tool_root(tmp_path, tool_name=name, host_capabilities=['deepseek_web', 'tool_catalog'])
    access = HostCapabilityAccessService()
    tokens = []
    def runner(command, input_text, cwd, env, timeout_seconds):
        token = env['TIANCE_HOST_CAPABILITY_TOKEN']
        tokens.append(token)
        grant = access.authorize(token, HostCapability.DEEPSEEK_WEB)
        assert grant is not None and grant.tool_name == name and grant.tool_project_id
        assert access.authorize(token, HostCapability.TOOL_CATALOG) == grant
        assert access.authorize(token, HostCapability.WEB_SEARCH) is None
        assert grant.run_id == 'run'
        assert 'TIANCE_GATEWAY_INTERNAL_TOKEN' not in env
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr='')
    service = ToolExecutionService(_FakeRegistry(root), command_runner=runner, host_capability_access=access)
    assert service.execute(ChatToolCall(call_id='call', name=name, arguments='{}'),
        context=ToolExecutionContext(run_id='run', enabled_tool_names=(name,))).ok
    assert access.authorize(tokens[0], HostCapability.TOOL_CATALOG) is None


def test_recognized_name_without_declaration_receives_no_authorization(tmp_path):
    root = _create_tool_root(tmp_path, tool_name='network_search')
    def runner(command, input_text, cwd, env, timeout_seconds):
        assert 'TIANCE_HOST_CAPABILITY_TOKEN' not in env
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr='')
    service = ToolExecutionService(_FakeRegistry(root), command_runner=runner)
    assert service.execute(ChatToolCall(call_id='call', name='network_search', arguments='{}'), context=ToolExecutionContext()).ok


@pytest.mark.parametrize('invalid', ['tool_catalog', [123], ['invented_capability'], None])
def test_bad_declaration_is_rejected_not_silently_discarded(invalid):
    with pytest.raises(ValueError):
        declared_host_capabilities({'type': 'python', 'host_capabilities': invalid})


def test_saved_manifest_preserves_declared_capabilities_and_sdk_catalog_is_complete():
    manifest = {'name': 'custom', 'registration_name': 'Custom', 'execution': {'parallel': True}, 'runtime': {
        'type': 'python', 'entry': 'program/main.py', 'timeout_seconds': 30,
        'host_capabilities': ['tool_catalog', 'deepseek_web']}}
    saved = ToolProjectConfigStorage().normalize_standard_file_content('.tool/tool.json', json.dumps(manifest))
    assert json.loads(saved)['runtime']['host_capabilities'] == ['tool_catalog', 'deepseek_web']
    assert {item['name'] for item in tiance_runtime.list_host_capabilities()} == {item.value for item in HOST_CAPABILITIES}


def test_renamed_github_tool_dispatches_by_capability_and_cannot_change_resource(bridge, monkeypatch):
    from app.services.application.github_platform import GithubPlatformService
    from tests.test_github_platform import _Github, _Projects
    service = GithubPlatformService(_Github(), _Projects())
    monkeypatch.setattr(github_platform, 'get_github_platform_service', lambda: service)
    grant = issue(bridge.access, tool_name='my_repository_helper', capabilities=(HostCapability.GITHUB_REPOSITORIES,))
    response = bridge.client.post('/api/github/platform/repositories',
        json={'action': 'list_repositories'}, headers=headers(grant))
    assert response.status_code == 200, response.text
    assert response.json()['tool'] == 'my_repository_helper'
    assert response.json()['resource'] == 'repositories'
    assert bridge.client.post('/api/github/platform/releases',
        json={'action': 'list'}, headers=headers(grant)).status_code == 401


def test_formal_tools_declare_every_capability_used_by_their_entrypoints():
    import ast
    from pathlib import Path
    tools = Path(__file__).resolve().parents[2] / 'Data/tools'
    for folder in tools.iterdir():
        manifest = folder / '.tool/tool.json'
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
        runtime = data.get('runtime', {})
        if runtime.get('type') != 'python':
            continue
        declared = set(declared_host_capabilities(runtime))
        entry = folder / runtime['entry']
        if not entry.is_file():
            continue
        for node in ast.walk(ast.parse(entry.read_text(encoding='utf-8-sig'))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'call_host_capability' and node.args
                    and isinstance(node.args[0], ast.Constant)):
                assert node.args[0].value in declared, (data['name'], node.args[0].value)


def test_dynamic_call_uses_actual_target_capabilities(tmp_path):
    from tests.test_dynamic_tool_execution import _GatewayRegistry, _executor_call
    registry = _GatewayRegistry(tmp_path)
    registry._metadata['theme_designer'].manifest['runtime']['host_capabilities'] = ['tool_catalog']
    access = HostCapabilityAccessService()
    tokens = []
    def runner(command, input_text, cwd, env, timeout_seconds):
        token = env['TIANCE_HOST_CAPABILITY_TOKEN']
        tokens.append(token)
        grant = access.authorize(token, HostCapability.TOOL_CATALOG)
        assert grant.tool_name == 'theme_designer'
        assert grant.tool_project_id == 'folder_theme_designer'
        assert grant.capabilities == frozenset({HostCapability.TOOL_CATALOG})
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr='')
    service = ToolExecutionService(registry, command_runner=runner, host_capability_access=access)
    result = service.execute(_executor_call('theme_designer', {'action': 'switch'}),
        context=ToolExecutionContext(enabled_tool_names=('theme_designer',)))
    assert result.ok and len(tokens) == 1
    assert access.authorize(tokens[0], HostCapability.TOOL_CATALOG) is None


@pytest.mark.parametrize('failure', ['result', 'exception'])
def test_execution_revokes_grant_on_failure(tmp_path, failure):
    root = _create_tool_root(tmp_path, tool_name='demo_tool', host_capabilities=['tool_catalog'])
    access = HostCapabilityAccessService()
    tokens = []
    def runner(command, input_text, cwd, env, timeout_seconds):
        tokens.append(env['TIANCE_HOST_CAPABILITY_TOKEN'])
        if failure == 'exception':
            raise OSError('failed to start process')
        return SimpleNamespace(returncode=1, stdout='{"ok":false,"error":"failed"}', stderr='')
    service = ToolExecutionService(_FakeRegistry(root), command_runner=runner, host_capability_access=access)
    call = ChatToolCall(call_id='failure', name='demo_tool', arguments='{}')
    if failure == 'exception':
        with pytest.raises(OSError):
            service.execute(call, context=ToolExecutionContext())
    else:
        assert not service.execute(call, context=ToolExecutionContext()).ok
    assert len(tokens) == 1
    assert access.authorize(tokens[0], HostCapability.TOOL_CATALOG) is None


def test_cancelled_real_process_revokes_grant(tmp_path):
    import sys
    import threading
    from pathlib import Path
    from app.services.tools.tool_execution_runtime import ToolExecutionCancellation
    root = _create_tool_root(tmp_path, tool_name='demo_tool', host_capabilities=['tool_catalog'])
    (root / 'program/main.py').write_text('import time; time.sleep(30)', encoding='utf-8')
    access = HostCapabilityAccessService()
    original_issue = access.issue_grant
    tokens = []
    issued = threading.Event()
    def capture(**kwargs):
        grant = original_issue(**kwargs)
        tokens.append(grant.token)
        issued.set()
        return grant
    access.issue_grant = capture
    cancellation = ToolExecutionCancellation()
    service = ToolExecutionService(_FakeRegistry(root), python_executable=Path(sys.executable), host_capability_access=access)
    results = []
    def execute():
        results.append(service.execute_cancellable(
            ChatToolCall(call_id='cancel', name='demo_tool', arguments='{}'),
            context=ToolExecutionContext(), cancellation=cancellation))
    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert issued.wait(5)
    finally:
        cancellation.cancel()
        thread.join(timeout=10)
    assert not thread.is_alive() and len(tokens) == 1
    assert len(results) == 1 and not results[0].ok
    assert access.authorize(tokens[0], HostCapability.TOOL_CATALOG) is None


def test_shipped_bridge_documentation_matches_installed_contracts():
    import ast
    import re
    from pathlib import Path
    document = (Path(__file__).resolve().parents[2] /
        'Data/tools/34b16133-f310-4064-b71f-f0411d13ab1d/assets/documentation/04-capability-bridges.md').read_text(encoding='utf-8')
    for name, definition in HOST_CAPABILITIES.items():
        assert f'| `{name.value}` | `{definition.path}` |' in document
    from app.schemas.llm.provider_capabilities import ProviderWebSearchRequestBody
    from app.schemas.github_platform import GithubPlatformToolRequest
    from app.schemas.github_sync import GithubSyncToolRequest
    from app.schemas.git_repository import GitRepositoryToolRequest
    from app.schemas.memory_management import MemoryManagementToolRequest
    schemas = {
        'web_search': ProviderWebSearchRequestBody, 'github_repositories': GithubPlatformToolRequest,
        'github_sync': GithubSyncToolRequest, 'git_repository': GitRepositoryToolRequest,
        'memory_management': MemoryManagementToolRequest, 'tool_catalog': routes.CatalogRequest,
        'run_status': routes.RunStatusRequest,
    }
    for code in re.findall(r'```python\n(.*?)\n```', document, re.DOTALL):
        for node in ast.walk(ast.parse(code)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'call_host_capability'):
                continue
            name = ast.literal_eval(node.args[0])
            assert HostCapability(name) in HOST_CAPABILITIES
            assert any(kw.arg == 'timeout_seconds' for kw in node.keywords)
            try:
                payload = ast.literal_eval(node.args[1])
            except ValueError:
                continue  # The full entry example reads tool_name from its input.
            if name in schemas:
                schemas[name].model_validate(payload)
