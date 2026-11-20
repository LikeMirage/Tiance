import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
sys.path.insert(0, str(PROGRAM_ROOT))
from package_environment import EnvironmentError, EnvironmentLock


class EnvironmentLockTests(unittest.TestCase):
    def test_killing_holder_releases_only_its_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (
                "import sys; from pathlib import Path; from package_environment import EnvironmentLock\n"
                "with EnvironmentLock(Path(sys.argv[1])):\n"
                "    print('locked', flush=True); sys.stdin.read()"
            )
            with subprocess.Popen(
                [sys.executable, "-c", script, str(root)], cwd=PROGRAM_ROOT,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            ) as child:
                try:
                    self.assertEqual(child.stdout.readline().strip(), "locked")
                    with EnvironmentLock(root / "other"):
                        with self.assertRaises(EnvironmentError) as busy:
                            with EnvironmentLock(root):
                                self.fail("second writer entered")
                        self.assertEqual(busy.exception.code, "ENVIRONMENT_BUSY")
                finally:
                    child.kill()
                    child.wait(timeout=10)
            with EnvironmentLock(root):
                pass

    def test_previous_version_respects_live_owner_and_recovers_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".package-manager.lock"
            with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                                  stdin=subprocess.PIPE) as child:
                try:
                    marker.write_text(f"pid={child.pid}\ncreated=1\n", encoding="ascii")
                    os.utime(marker, (1, 1))
                    with self.assertRaises(EnvironmentError) as busy:
                        with EnvironmentLock(root):
                            self.fail("live legacy writer was ignored")
                    self.assertEqual(busy.exception.code, "ENVIRONMENT_BUSY")
                    self.assertTrue(marker.exists())
                finally:
                    child.kill()
                    child.wait(timeout=10)
            os.utime(marker)
            with EnvironmentLock(root):
                self.assertFalse(marker.exists())
