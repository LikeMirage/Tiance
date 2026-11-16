"""Sample only this desktop's process tree, without recording command lines."""
import ctypes
import os
import sys

import psutil


def collect_process_metrics():
    memory = psutil.virtual_memory()
    system = {"physical_total": memory.total, "physical_available": memory.available}
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "physical_total", "physical_available", "commit_limit", "commit_available",
                    "virtual_total", "virtual_available", "extended_available")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            system.update(commit_limit=status.commit_limit, commit_available=status.commit_available)
    root = psutil.Process(os.getpid())
    processes, unavailable = [], 0
    for process in [root, *root.children(recursive=True)]:
        try:
            with process.oneshot():
                info = process.memory_info()
                name = process.name().lower()
                kind = "shell" if process.pid == root.pid else "other"
                if "msedgewebview2" in name:
                    kind = "webview_browser"
                    # Inspect only the process type; never persist arguments or URLs.
                    types = {"renderer", "gpu-process", "utility", "crashpad-handler"}
                    for argument in process.cmdline():
                        if argument.startswith("--type=") and argument[7:] in types:
                            kind = "webview_" + argument[7:]
                elif process.pid != root.pid:
                    kind = "python" if name in {"python.exe", "pythonw.exe", "python", "python3"} else "gateway" if name == "tiancegateway.exe" else "other"
                processes.append(dict(pid=process.pid, parent=process.ppid(), kind=kind,
                    started=process.create_time(), rss=info.rss, private=getattr(info, "private", None),
                    vms=info.vms, peak_rss=getattr(info, "peak_wset", None), threads=process.num_threads()))
        except (psutil.Error, OSError):
            unavailable += 1
    # A tool may start many children. Keep totals for all, details for the largest 64.
    return dict(system=system, process_count=len(processes), unavailable=unavailable,
                rss_total=sum(p["rss"] for p in processes),
                private_total=sum(p["private"] or 0 for p in processes),
                processes=sorted(processes, key=lambda p: p["private"] or p["rss"], reverse=True)[:64])
