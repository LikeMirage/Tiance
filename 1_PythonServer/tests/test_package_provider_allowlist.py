import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = ("manifest.json", "provider.json", "provider-rules.json", "model-rules.json", "models.json")


def _run(repo, *args):
    return subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")


def _write(repo, relative, content):
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def package_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _write(repo, ".gitattributes", (ROOT / ".gitattributes").read_text(encoding="utf-8-sig"))
    for name in ("package-release.ps1", "package-test.ps1", "package-providers.ps1",
                 "build-remote-gateway.ps1", "gateway-build-integrity.ps1"):
        target = repo / "scripts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "scripts" / name, target)
    _write(repo, "scripts/package-providers.json", json.dumps({"schemaVersion": 1, "providerIds": ["public"]}))
    for relative in ("Tiance.exe", "LICENSE", "runtime/gateway/TianceRemoteGateway.exe",
                     "1_PythonServer/run.py", "2_ReactWeb/dist/index.html", "3_PyWebView/run.py"):
        _write(repo, relative, "fixture")
    _write(repo, "system/version.json", '{"version":"0.1.0"}')
    for provider in ("public", "private"):
        for name in PUBLIC_FILES:
            _write(repo, f"Data/providers/{provider}/{name}", json.dumps({"id": provider}))
        for name in ("credentials.json", "cloud-model-cache.json", "notes.txt"):
            _write(repo, f"Data/providers/{provider}/{name}", "fixture-private-data")
    _write(repo, "Data/providers/provider-settings.json", json.dumps({
        "schemaVersion": 1, "providerOrder": ["private", "public"], "providerPresetCatalogVersion": 2,
    }))
    _write(repo, "Data/providers/catalog.json", '{"private":"local index"}')
    _write(repo, "3_PyWebView/gateway/windows/TianceRemoteGateway/TianceRemoteGateway.csproj", "<Project />")
    _write(repo, "3_PyWebView/gateway/windows/TianceRemoteGateway/Program.cs", "// fixture\n")
    _write_gateway_receipt(repo)
    _commit(repo)
    _run(repo, "git", "tag", "v0.1.0")
    _write(repo, "system/version.json", '{"version":"0.2.0"}')
    _commit(repo)
    _run(repo, "git", "tag", "v0.2.0")
    return repo


def _write_gateway_receipt(repo):
    paths = [*sorted((repo / "3_PyWebView/gateway/windows/TianceRemoteGateway").glob("*")),
             repo / "scripts/build-remote-gateway.ps1", repo / "scripts/gateway-build-integrity.ps1"]
    executable = (repo / "runtime/gateway/TianceRemoteGateway.exe").read_bytes()
    _write(repo, "runtime/gateway/build-manifest.json", json.dumps({
        "schemaVersion": 1, "runtimeIdentifier": "win-x64", "sdkVersion": "fixture",
        "sources": [{"path": p.relative_to(repo).as_posix(),
                     "sha256": hashlib.sha256(p.read_text(encoding="utf-8-sig").encode()).hexdigest()} for p in paths],
        "artifact": {"path": "runtime/gateway/TianceRemoteGateway.exe", "size": len(executable),
                     "sha256": hashlib.sha256(executable).hexdigest()},
    }))


@pytest.mark.parametrize("change", ["source", "new_source", "binary", "missing_receipt", "missing_source", "build_script"])
@pytest.mark.parametrize("script", ["package-test.ps1", "package-release.ps1"])
def test_mismatched_gateway_stops_packaging(package_repo, change, script):
    repo = package_repo
    if change == "source":
        _write(repo, "3_PyWebView/gateway/windows/TianceRemoteGateway/Program.cs", "// changed")
    elif change == "new_source":
        _write(repo, "3_PyWebView/gateway/windows/TianceRemoteGateway/New.cs", "// new")
    elif change == "binary":
        _write(repo, "runtime/gateway/TianceRemoteGateway.exe", "old-exe")
    elif change == "missing_receipt":
        (repo / "runtime/gateway/build-manifest.json").unlink()
    elif change == "missing_source":
        (repo / "3_PyWebView/gateway/windows/TianceRemoteGateway/Program.cs").unlink()
    else:
        with (repo / "scripts/build-remote-gateway.ps1").open("a") as f:
            f.write("\n# changed build flags\n")
    _commit(repo)
    args = ("-Version", "0.2.0", "-Tag", "HEAD", "-PreviousTag", "v0.1.0") if script == "package-release.ps1" else ()
    result = _package(repo, script, *args, "-OutputDirectory", "rejected", check=False)
    assert result.returncode != 0
    assert "Gateway" in result.stdout + result.stderr
    assert not (repo / "rejected/Tiance.zip").exists()
    assert not (repo / "rejected/Tiance").exists()


def test_gateway_check_uses_selected_snapshot_and_normalizes_line_endings(package_repo):
    repo = package_repo
    source = repo / "3_PyWebView/gateway/windows/TianceRemoteGateway/Program.cs"
    source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    _write(repo, "scripts/verify-fixture.ps1", '$ErrorActionPreference = "Stop"\n'
           '. (Join-Path $PSScriptRoot "gateway-build-integrity.ps1")\n'
           'Assert-GatewayBuild -Root (Split-Path -Parent $PSScriptRoot)\n')
    _package(repo, "verify-fixture.ps1")
    # Later workspace changes must not contaminate validation of committed inputs.
    source.write_text("// uncommitted change", encoding="utf-8")
    _package(repo, "package-test.ps1", "-OutputDirectory", "verified")
    assert (repo / "verified/Tiance/runtime/gateway/build-manifest.json").is_file()
    assert not (repo / "verified/Tiance/scripts").exists()


def test_failed_gateway_build_preserves_previous_runtime(package_repo):
    repo = package_repo
    previous_exe = (repo / "runtime/gateway/TianceRemoteGateway.exe").read_bytes()
    previous_receipt = (repo / "runtime/gateway/build-manifest.json").read_bytes()
    _write(repo, "fake-dotnet.ps1", 'if ($args[0] -eq "--version") { Write-Output "8.0.fake"; exit 0 }; exit 1')
    result = _package(repo, "build-remote-gateway.ps1", "-DotnetPath", str(repo / "fake-dotnet.ps1"), check=False)
    assert result.returncode != 0
    assert "publish failed" in result.stdout + result.stderr
    assert (repo / "runtime/gateway/TianceRemoteGateway.exe").read_bytes() == previous_exe
    assert (repo / "runtime/gateway/build-manifest.json").read_bytes() == previous_receipt


def _commit(repo):
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "-c", "user.name=Package Test", "-c", "user.email=package@example.invalid",
         "commit", "-qm", "fixture")


def _package(repo, script, *args, check=True, shell_name=None):
    shell = shutil.which(shell_name) if shell_name else (shutil.which("pwsh") or shutil.which("powershell"))
    if shell is None:
        pytest.skip("PowerShell is required for packaging tests")
    environment = os.environ.copy()
    environment.pop("GIT_INDEX_FILE", None)
    # A Python child of pwsh otherwise forwards PS7 module paths into Windows PowerShell 5.1.
    for key in list(environment):
        if key.casefold() == "psmodulepath":
            environment.pop(key)
    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(repo / "scripts" / script), *args],
        cwd=repo, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def _assert_public_files(names, read):
    provider_names = {name for name in names if name.startswith("Data/providers/") and not name.endswith("/")}
    assert provider_names == {"Data/providers/provider-settings.json", *[
        f"Data/providers/public/{name}" for name in PUBLIC_FILES
    ]}
    settings = json.loads(read("Data/providers/provider-settings.json"))
    assert settings["providerOrder"] == ["public"]
    assert settings["providerPresetCatalogVersion"] == 2


def test_release_filters_even_committed_private_files_without_changing_source(package_repo):
    repo = package_repo
    before = {p: p.read_bytes() for p in (repo / "Data/providers").rglob("*") if p.is_file()}
    index_before = (repo / ".git/index").read_bytes()
    _package(repo, "package-release.ps1", "-Version", "0.2.0", "-Tag", "v0.2.0",
             "-PreviousTag", "v0.1.0", "-OutputDirectory", "output")
    with zipfile.ZipFile(repo / "output/Tiance.zip") as archive:
        _assert_public_files([name.removeprefix("Tiance/") for name in archive.namelist()],
                             lambda name: archive.read("Tiance/" + name))
    for name in ("Tiance-update.zip", "Tiance-update-incremental.zip"):
        with zipfile.ZipFile(repo / "output" / name) as archive:
            assert not any("/Data/" in path for path in archive.namelist())
    assert all(p.read_bytes() == content for p, content in before.items())
    assert (repo / ".git/index").read_bytes() == index_before


@pytest.mark.parametrize("shell_name", ["powershell", "pwsh"])
def test_release_json_is_accepted_by_current_updater(package_repo, shell_name):
    from app.services.application.software_update import _extract_update_archive, _validate_staged_payload

    repo = package_repo
    _package(repo, "package-release.ps1", "-Version", "0.2.0", "-Tag", "v0.2.0",
             "-PreviousTag", "v0.1.0", "-OutputDirectory", "output", shell_name=shell_name)
    index = json.loads((repo / "output/update.json").read_text(encoding="utf-8"))
    assert index["version"] == "0.2.0"
    for name in ("Tiance-update.zip", "Tiance-update-incremental.zip"):
        stage = repo / f"stage-{name}"
        _extract_update_archive(repo / "output" / name, stage)
        _validate_staged_payload(stage / "Tiance", "0.2.0")
        assert (stage / "Tiance/.tiance-update-ready").read_text(encoding="utf-8") == "0.2.0"


def test_working_tree_test_package_filters_providers_and_preserves_local_edits(package_repo):
    repo = package_repo
    _write(repo, "Data/providers/new-private/provider.json", '{"id":"new-private"}')
    index_before = (repo / ".git/index").read_bytes()
    _package(repo, "package-test.ps1", "-WorkingTreePaths", "Data/providers", "-OutputDirectory", "test-output")
    target = repo / "test-output/Tiance"
    _assert_public_files([p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()],
                         lambda name: (target / name).read_bytes())
    assert (repo / "Data/providers/new-private/provider.json").is_file()
    assert (repo / ".git/index").read_bytes() == index_before


@pytest.mark.parametrize("policy", [None, {"schemaVersion": 1, "providerIds": ["../private"]},
                                    {"schemaVersion": 1, "providerIds": ["missing"]}])
def test_missing_or_invalid_policy_stops_packaging(package_repo, policy):
    repo = package_repo
    if policy is None:
        (repo / "scripts/package-providers.json").unlink()
    else:
        _write(repo, "scripts/package-providers.json", json.dumps(policy))
    _commit(repo)
    result = _package(repo, "package-test.ps1", "-OutputDirectory", "bad-output", check=False)
    assert result.returncode != 0
    assert not (repo / "bad-output/Tiance").exists()


@pytest.mark.parametrize("package_kind", ["release", "test"])
def test_tool_config_templates_are_published_but_backups_are_excluded(package_repo, package_kind):
    repo = package_repo
    program = "Data/tools/ea5cace1-0644-4ecf-ac63-02e4b88b05b4/program/"
    tool_ids = (
        "ea5cace1-0644-4ecf-ac63-02e4b88b05b4",
        "c91ee7e1-052e-584e-b665-2d79945aa923",
        "31084ec1-b544-4654-a09a-2021b6406a70",
        "d915c8c7-8315-4de1-b61c-c29b77a5a6d5",
    )
    public_files = [f"Data/tools/{tool_id}/program/config.json" for tool_id in tool_ids]
    private_files = [
        f"Data/tools/{tool_id}/program/{name}"
        for tool_id in tool_ids
        for name in ("config.json.bak", "config.json.backup")
    ]
    private_files.append(".Tiance/tool-config-backups/fixture/" + program + "config.json")
    template = {"provider": {"api_key": "", "base_url": "https://example.invalid/v1", "model": "fixture-model"}}
    for name in public_files:
        _write(repo, name, json.dumps(template))
    for name in private_files:
        _write(repo, name, '{"provider":{"api_key":"fixture-secret"}}')
    _write(repo, program + "main.py", "# public tool entry")
    _write(repo, program + "config_loader.py", "# public configuration loader")
    # Deliberately track the backups: archive exclusion must not rely on .gitignore.
    _commit(repo)
    _run(repo, "git", "tag", "v0.2.1")
    before = {name: (repo / name).read_bytes() for name in public_files + private_files}
    if package_kind == "release":
        _package(repo, "package-release.ps1", "-Version", "0.2.0", "-Tag", "v0.2.1",
                 "-PreviousTag", "v0.2.0", "-OutputDirectory", "tool-release")
        with zipfile.ZipFile(repo / "tool-release/Tiance.zip") as archive:
            names = {name.removeprefix("Tiance/") for name in archive.namelist()}
            assert all(json.loads(archive.read("Tiance/" + name)) == template for name in public_files)
        for name in ("Tiance-update.zip", "Tiance-update-incremental.zip"):
            with zipfile.ZipFile(repo / "tool-release" / name) as archive:
                assert not any("/Data/" in path for path in archive.namelist())
    else:
        _package(repo, "package-test.ps1", "-WorkingTreePaths", "Data/tools", "-OutputDirectory", "tool-test")
        target = repo / "tool-test/Tiance"
        names = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
        assert all(json.loads((target / name).read_text(encoding="utf-8")) == template for name in public_files)
    assert set(public_files).issubset(names)
    assert not set(private_files).intersection(names)
    assert program + "main.py" in names
    assert program + "config_loader.py" in names
    assert all((repo / name).read_bytes() == data for name, data in before.items())


def test_database_search_recreates_config_without_a_key(tmp_path):
    program = ROOT / "Data/tools/ea5cace1-0644-4ecf-ac63-02e4b88b05b4/program"
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "import config_loader as c; c.CONFIG_PATH = Path(sys.argv[2]); "
        "c.ensure_config_file_exists(); "
        "assert c.load_tool_config().provider.api_key == ''",
        str(program), str(tmp_path / "config.json"),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["siliconflow"]["api_key"] == ""
