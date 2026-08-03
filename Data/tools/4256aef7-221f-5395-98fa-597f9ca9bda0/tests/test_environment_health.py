from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ROOT = TOOL_ROOT / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

from candidate_environment import CandidateEnvironment  # noqa: E402
from environment_health import inspect_environment  # noqa: E402
from package_environment import EnvironmentError  # noqa: E402
from windows_permissions import (  # noqa: E402
    PermissionManagementError,
    PermissionRepairResult,
    inspect_protected_paths,
    reset_package_permissions,
    validate_managed_packages_root,
)


def _tool_packages_root(temp_dir: str) -> Path:
    root = Path(temp_dir) / "Data" / "tools" / "tool-id" / "dependencies" / "py313"
    (root / "site-packages").mkdir(parents=True)
    return root


class EnvironmentHealthTests(unittest.TestCase):
    def test_permission_root_rejects_unrelated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(PermissionManagementError) as raised:
                validate_managed_packages_root(Path(temp_dir))
            self.assertEqual(raised.exception.code, "UNSAFE_PERMISSION_ROOT")

    def test_candidate_retries_after_scoped_permission_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _tool_packages_root(temp_dir)
            source = root / "site-packages"
            (source / "marker.txt").write_text("kept", encoding="utf-8")
            real_copytree = shutil.copytree
            attempts = 0

            def flaky_copytree(src: Path, dst: Path) -> Path:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError(5, "access denied")
                return real_copytree(src, dst)

            repair = PermissionRepairResult(True, 0, "", "", True)
            with patch("candidate_environment.shutil.copytree", side_effect=flaky_copytree), patch(
                "candidate_environment.reset_package_permissions",
                return_value=repair,
            ):
                with CandidateEnvironment(root) as candidate:
                    assert candidate.path is not None
                    self.assertEqual(
                        (candidate.path / "marker.txt").read_text(encoding="utf-8"),
                        "kept",
                    )
                    self.assertEqual(len(candidate.preparation_warnings), 1)
            self.assertEqual(attempts, 2)

    def test_candidate_returns_stable_error_when_repair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _tool_packages_root(temp_dir)
            repair = PermissionRepairResult(True, 5, "denied", "", False)
            with patch(
                "candidate_environment.shutil.copytree",
                side_effect=OSError(5, "access denied"),
            ), patch(
                "candidate_environment.reset_package_permissions",
                return_value=repair,
            ):
                with self.assertRaises(EnvironmentError) as raised:
                    CandidateEnvironment(root).__enter__()
            self.assertEqual(
                raised.exception.code,
                "ENVIRONMENT_PERMISSION_REPAIR_FAILED",
            )
            self.assertTrue(raised.exception.details["requires_elevation"])

    def test_health_report_marks_protected_paths_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _tool_packages_root(temp_dir)
            protected = root / "site-packages" / "protected-package"
            protected.mkdir()
            with patch(
                "environment_health.inspect_protected_paths",
                return_value=(protected,),
            ):
                report = inspect_environment(root)
            self.assertFalse(report.healthy)
            self.assertTrue(report.clone_probe_succeeded)
            self.assertEqual(report.protected_paths, (protected,))

    def test_health_report_marks_failed_candidate_residue_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _tool_packages_root(temp_dir)
            residue = root / "environments" / ".candidate-leftover"
            residue.mkdir(parents=True)
            report = inspect_environment(root)
            self.assertFalse(report.healthy)
            self.assertEqual(report.candidate_directories, (residue,))
            self.assertIn(
                "FAILED_CANDIDATE_RESIDUE",
                {issue["code"] for issue in report.issues},
            )

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_windows_acl_repair_is_scoped_and_verifiable(self) -> None:
        icacls = shutil.which("icacls")
        if not icacls:
            self.skipTest("icacls is unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _tool_packages_root(temp_dir)
            protected = root / "site-packages" / "protected-package"
            protected.mkdir()
            changed = subprocess.run(
                [icacls, str(protected), "/inheritance:d", "/Q"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(changed.returncode, 0)
            before = inspect_protected_paths(root, (protected,))
            self.assertEqual(before, (protected.resolve(),))
            repaired = reset_package_permissions(root)
            self.assertTrue(repaired.succeeded)
            after = inspect_protected_paths(root, (protected,))
            self.assertEqual(after, ())


if __name__ == "__main__":
    unittest.main()
