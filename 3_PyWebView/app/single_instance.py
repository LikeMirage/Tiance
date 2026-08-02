import os
from pathlib import Path
import time

from app.startup_timing import mark


LOCK_FILE = "tiance-desktop-shell.lock"
DEFAULT_WINDOW_TITLE = "Tiance"
FOCUS_RETRY_COUNT = 12
FOCUS_RETRY_INTERVAL_SECONDS = 0.15


class SingleInstanceLock:
    def __init__(self, lock_file: Path) -> None:
        self.lock_file = lock_file
        self._handle = lock_file.open("a+b")

    def acquire(self) -> bool:
        self._handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.close()
            return False

        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()).encode("ascii"))
        self._handle.flush()
        return True

    def close(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()


def acquire_single_instance_lock(project_root: Path) -> SingleInstanceLock | None:
    lock_dir = project_root / "Data" / "cache" / "desktop-shell"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = SingleInstanceLock(lock_dir / LOCK_FILE)
    if lock.acquire():
        mark("single instance lock: acquired", path=str(lock.lock_file), pid=os.getpid())
        return lock

    mark("single instance lock: already running", path=str(lock.lock_file))
    return None


def notify_existing_instance(project_root: Path) -> None:
    if os.name == "nt" and focus_existing_instance(project_root):
        print("天策已在运行，已切换到已有窗口。", flush=True)
        return

    message = "天策已在运行，请从任务栏切回已有窗口。"
    print(message, flush=True)
    if os.name != "nt" or os.getenv("TIANCE_SHELL_SUPPRESS_SINGLE_INSTANCE_MESSAGE"):
        return

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Tiance", 0x40)
    except Exception:
        return


def focus_existing_instance(project_root: Path) -> bool:
    if os.name != "nt":
        return False

    window_title = os.getenv("TIANCE_SHELL_TITLE", DEFAULT_WINDOW_TITLE)
    owner_pid = _read_lock_owner_pid(project_root)

    for _ in range(FOCUS_RETRY_COUNT):
        hwnd = _find_existing_window(project_root, window_title, owner_pid)
        if hwnd and _activate_window(hwnd):
            mark("single instance lock: existing window focused", hwnd=hwnd)
            return True
        time.sleep(FOCUS_RETRY_INTERVAL_SECONDS)

    mark("single instance lock: existing window not found", owner_pid=owner_pid or "<unknown>")
    return False


def _read_lock_owner_pid(project_root: Path) -> int | None:
    lock_file = project_root / "Data" / "cache" / "desktop-shell" / LOCK_FILE
    try:
        raw_pid = lock_file.read_text(encoding="ascii").strip()
        owner_pid = int(raw_pid)
    except (OSError, ValueError):
        return None

    return owner_pid if owner_pid > 0 else None


def _find_existing_window(project_root: Path, window_title: str, owner_pid: int | None) -> int | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    matches: list[int] = []

    def enum_window(hwnd: int, _lparam: int) -> bool:
        title = _get_window_title(hwnd)
        if title != window_title:
            return True

        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        pid = int(window_pid.value)
        if owner_pid is not None and pid == owner_pid:
            matches.append(hwnd)
            return False
        if owner_pid is None and _looks_like_desktop_shell_process(pid, project_root):
            matches.append(hwnd)
            return False

        return True

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_window)
    user32.EnumWindows(enum_proc, 0)
    return matches[0] if matches else None


def _get_window_title(hwnd: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _looks_like_desktop_shell_process(pid: int, project_root: Path) -> bool:
    try:
        import psutil

        process = psutil.Process(pid)
        command_line = " ".join(process.cmdline()).casefold()
    except Exception:
        return False

    run_py = str(project_root / "3_PyWebView" / "run.py").casefold()
    return run_py in command_line


def _activate_window(hwnd: int) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_SHOW = 5
    SW_RESTORE = 9
    HWND_TOP = 0
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040

    target_pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
    current_thread = kernel32.GetCurrentThreadId()
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground_hwnd, None)
        if foreground_hwnd
        else 0
    )

    attached_target = False
    attached_foreground = False
    try:
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            )

        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        focused = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)

    if focused:
        return True

    try:
        user32.FlashWindow(hwnd, True)
    except Exception:
        pass
    return False
