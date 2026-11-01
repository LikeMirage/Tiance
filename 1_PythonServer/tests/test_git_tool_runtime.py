"""Exercise the shipped Git tool through the production subprocess launcher."""

from json import dumps, loads
from pathlib import Path
import shutil
import subprocess
import sys

from dulwich import porcelain
from dulwich.repo import Repo
import pytest

from app.services.tools.tool_execution_runtime import build_python_command, build_tool_env


@pytest.mark.parametrize("key", ["USERNAME", "USER", "LOGNAME", "LNAME"])
def test_tool_environment_preserves_existing_system_username(key, monkeypatch):
    monkeypatch.setenv(key, "local-user")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "unrelated@example.test")
    monkeypatch.setenv("GITHUB_TOKEN", "unrelated-secret")
    env = build_tool_env(python_paths=(), workspace_root=None)
    assert env.get(key) == "local-user"
    assert "GIT_AUTHOR_EMAIL" not in env
    assert "GITHUB_TOKEN" not in env


def test_clone_in_tool_process_needs_no_git_author_or_system_git(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    program = root / "Data/tools/b0bd4302-4875-4e7a-94a2-07a21b130d4a/program"
    # Copy code only: never use or change the installed tool's credentials/configuration.
    isolated_program = tmp_path / "program"
    isolated_program.mkdir()
    for source in program.glob("*.py"):
        shutil.copy2(source, isolated_program / source.name)
    (isolated_program / "config.json").write_text("{}", encoding="utf-8")

    seed = tmp_path / "seed"
    seed.mkdir()
    porcelain.init(seed).close()
    (seed / "README.md").write_text("clone fixture\n", encoding="utf-8")
    porcelain.add(seed, paths=["README.md"])
    identity = b"Fixture Author <fixture@example.test>"
    expected_head = porcelain.commit(seed, message=b"fixture", author=identity, committer=identity)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    for key in ("USER", "LOGNAME", "LNAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("USERNAME", "local-user")
    for key in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(key, str(empty_home))
    paths = (isolated_program, *(Path(p) for p in sys.path if p))
    command = build_python_command(
        python_executable=Path(sys.executable),
        entry_path=isolated_program / "main.py",
        python_paths=paths,
    )

    def invoke(payload, directory):
        env = build_tool_env(python_paths=paths, workspace_root=directory)
        env["PATH"] = ""  # A system Git installation must not be needed.
        completed = subprocess.run(
            command, input=dumps(payload), cwd=directory, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        result = loads(completed.stdout)
        assert completed.returncode == (0 if result["ok"] else 1), completed.stderr
        return result

    result = invoke({"action": "clone", "repository": str(seed), "target_path": "cloned"}, workspace)
    assert result["ok"], result
    cloned = workspace / "cloned"
    assert (cloned / "README.md").read_text(encoding="utf-8") == "clone fixture\n"
    with Repo(cloned) as repo:
        assert repo.head() == expected_head
        assert any(
            list(repo.read_reflog(ref))
            for ref in repo.refs.keys() if ref.startswith(b"refs/remotes/origin/")
        )
        for field in (b"name", b"email"):
            with pytest.raises(KeyError):
                repo.get_config().get((b"user",), field)

    # The OS username is only enough for local bookkeeping, not an approved commit author.
    (cloned / "README.md").write_text("changed\n", encoding="utf-8")
    commit = invoke({"action": "commit", "message": "must require author"}, cloned)
    assert not commit["ok"]
    assert commit["error_info"]["code"] == "GIT_IDENTITY_MISSING"
