from pathlib import Path
import tempfile
import unittest

from app.backend_process_log import (
    MAX_BACKEND_LOG_BYTES,
    PREVIOUS_BACKEND_LOG_NAME,
    backend_log_path,
    open_backend_process_log,
)


class BackendProcessLogTests(unittest.TestCase):
    def test_oversized_log_is_rotated_before_backend_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            current_log = backend_log_path(project_root)
            current_log.parent.mkdir(parents=True)
            current_log.write_bytes(b"x" * (MAX_BACKEND_LOG_BYTES + 1))

            with open_backend_process_log(project_root) as stream:
                stream.write(b"new backend run\n")

            previous_log = current_log.with_name(PREVIOUS_BACKEND_LOG_NAME)
            self.assertEqual(previous_log.stat().st_size, MAX_BACKEND_LOG_BYTES + 1)
            self.assertEqual(current_log.read_bytes(), b"new backend run\n")


if __name__ == "__main__":
    unittest.main()
