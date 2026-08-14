from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
sys.path.insert(0, str(PROGRAM_ROOT))

from configuration import GitIdentity, ToolConfiguration, authentication_summary  # noqa: E402
from git_adapter import GitRepositoryAdapter  # noqa: E402
import service  # noqa: E402


IDENTITY = GitIdentity("Tiance Test", "tiance@example.com", "test")


class GitToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.previous_workspace = os.environ.get("TIANCE_WORKSPACE_ROOT")
        os.environ["TIANCE_WORKSPACE_ROOT"] = str(self.root)

    def tearDown(self) -> None:
        if self.previous_workspace is None:
            os.environ.pop("TIANCE_WORKSPACE_ROOT", None)
        else:
            os.environ["TIANCE_WORKSPACE_ROOT"] = self.previous_workspace
        self.temporary.cleanup()

    def test_commit_preview_reports_resolved_identity_and_excludes_tiance_metadata(self) -> None:
        self.assertTrue(service.execute({"action": "init", "branch": "main"})["ok"])
        configured = service.execute(
            {
                "action": "configure_identity",
                "identity_scope": "repository",
                "author_name": "Repository User",
                "author_email": "repository@example.com",
            }
        )
        self.assertTrue(configured["ok"])
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        metadata = self.root / ".Tiance"
        metadata.mkdir()
        (metadata / "state.json").write_text("{}", encoding="utf-8")

        preview = service.execute(
            {"action": "commit", "message": "initial", "dry_run": True}
        )

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["preview"]["identity"]["source"], "repository")
        self.assertEqual(
            preview["preview"]["changes"],
            [{"path": "README.md", "state": "untracked"}],
        )
        committed = service.execute({"action": "commit", "message": "initial"})
        self.assertTrue(committed["ok"])
        self.assertEqual(len(committed["commitSha"]), 40)

    def test_explicit_commit_identity_overrides_repository_identity(self) -> None:
        adapter = GitRepositoryAdapter(self.root)
        adapter.init(branch="main")
        repo = adapter.open()
        try:
            config = repo.get_config()
            config.set((b"user",), b"name", b"Wrong Default")
            config.set((b"user",), b"email", b"wrong@example.com")
            config.write_to_path()
        finally:
            repo.close()
        (self.root / "file.txt").write_text("content", encoding="utf-8")

        preview = service.execute(
            {
                "action": "commit",
                "message": "explicit",
                "author_name": "Chosen User",
                "author_email": "chosen@example.com",
                "dry_run": True,
            }
        )

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["preview"]["identity"]["name"], "Chosen User")
        self.assertEqual(preview["preview"]["identity"]["source"], "operation")
        self.assertEqual(preview["preview"]["identityCandidates"][1]["name"], "Wrong Default")

    def test_local_remote_push_and_clone_need_no_login_or_system_git(self) -> None:
        remote = self.root / "remote.git"
        work = self.root / "seed"
        remote.mkdir()
        work.mkdir()

        from dulwich import porcelain

        porcelain.init(remote, bare=True).close()
        seed = GitRepositoryAdapter(work)
        seed.init(branch="main")
        (work / "README.md").write_text("seed", encoding="utf-8")
        seed.commit(message="seed", paths=None, identity=IDENTITY)
        seed.add_remote(name="origin", url=str(remote))
        seed.push(remote="origin", branch="main", credential=None)

        cloned = service.execute(
            {
                "action": "clone",
                "repository": str(remote),
                "target_path": "cloned",
                "branch": "main",
            }
        )

        self.assertTrue(cloned["ok"])
        self.assertFalse(cloned["systemGitRequired"])
        self.assertEqual((self.root / "cloned" / "README.md").read_text(encoding="utf-8"), "seed")

    def test_https_credential_summary_never_returns_token(self) -> None:
        config_path = self.root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "https_credentials": [
                        {
                            "host": "example.com",
                            "username": "token-user",
                            "token": "top-secret-token",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        summary = authentication_summary(
            "https://example.com/private/repo.git",
            ToolConfiguration(config_path),
        )

        self.assertEqual(summary, {"kind": "https", "available": True, "source": "tool_config"})
        self.assertNotIn("top-secret-token", json.dumps(summary))

    def test_clone_target_cannot_escape_workspace(self) -> None:
        result = service.execute(
            {
                "action": "clone",
                "repository": "https://example.com/project.git",
                "target_path": "../outside",
                "dry_run": True,
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "PATH_OUTSIDE_WORKSPACE")

    def test_new_remote_rejects_credentials_embedded_in_url(self) -> None:
        result = service.execute(
            {
                "action": "clone",
                "repository": "https://user:secret@example.com/project.git",
                "dry_run": True,
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "CREDENTIAL_IN_URL")
        self.assertNotIn("secret", json.dumps(result))

    def test_path_scoped_commit_rejects_other_staged_changes(self) -> None:
        from dulwich import porcelain

        adapter = GitRepositoryAdapter(self.root)
        adapter.init(branch="main")
        (self.root / "first.txt").write_text("first", encoding="utf-8")
        (self.root / "second.txt").write_text("second", encoding="utf-8")
        porcelain.add(str(self.root), paths=["second.txt"])

        result = service.execute(
            {
                "action": "commit",
                "message": "only first",
                "paths": ["first.txt"],
                "author_name": "Chosen User",
                "author_email": "chosen@example.com",
            }
        )

        self.assertFalse(result["ok"])
        self.assertIn("paths 之外", result["error"])


if __name__ == "__main__":
    unittest.main()
