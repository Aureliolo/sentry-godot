"""Checks that a game still crashes when its crash handler stops answering, and never hangs.

    python scripts/check-handler-stall.py <godot> [<godot> ...] [--addon <dir>] [--limit 150]

Runs a headless project carrying the addon (project/addons/sentry as the builds left it, or the
folder --addon names) that crashes on purpose a second after the SDK is up. Each Godot runs it
four times. The first leaves the SDK uninitialised, for the exit code the engine gives a crash on
its own. The second leaves the crash handler alone and must leave a minidump. The third suspends
the run's own crashpad_handler as it starts, and the fourth once the SDK is up. These two must end
within the limit, with the exit code of the second run or of the first. A handler that never
answered its start leaves the crash to the engine, so on Linux it ends as the first run does. Only
a handler started by this run is touched, and it is resumed and ended by its pid.
"""

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_clean_exit", HERE / "check-clean-exit.py")
assert spec is not None and spec.loader is not None
clean_exit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean_exit)

CRASH = (
    'extends SceneTree\n\n\nfunc _initialize() -> void:\n\tprint("quit.gd up")\n'
    '\tawait create_timer(1.0).timeout\n\tprint("CRASHING NOW")\n'
    "\tSentrySDK.bad_code.crash_with_null_dereference()\n"
)
# The DSN points nowhere that answers, so the SDK starts and sends nothing.
SETTINGS = '\n[sentry]\n\noptions/dsn="https://public@127.0.0.1:9/1"\n'
UP = b"quit.gd up"
CASES = ("without the SDK", "never", "as it starts", "once up")


class Handlers:
    """Finds, suspends, resumes and ends the crash handlers one run started."""

    def __init__(self, engine: subprocess.Popen, scratch: str):
        self.engine = engine
        self.scratch = scratch
        self.suspended: list[int] = []
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.ntdll = ctypes.WinDLL("ntdll")
            self.kernel32.OpenProcess.restype = wintypes.HANDLE
            self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            self.kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            self.kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            self.kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self.ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
            self.ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            self.handles: dict[int, int] = {}

    def find(self) -> list[int]:
        if sys.platform == "win32":
            return [pid for pid, (parent, exe) in self._windows_processes().items()
                    if parent == self.engine.pid and exe == "crashpad_handler.exe"]
        # The Linux handler is started through a double fork, so it is found by its database path,
        # which lies in this run's own temporary folder.
        found = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                argv = Path(f"/proc/{entry}/cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if argv[0].endswith(b"crashpad_handler") and any(self.scratch.encode() in a for a in argv):
                found.append(int(entry))
        return found

    def suspend(self, pid: int) -> None:
        if sys.platform == "win32":
            handle = self.kernel32.OpenProcess(0x0800 | 0x0001, False, pid)  # suspend-resume, terminate
            self.handles[pid] = handle
            self.ntdll.NtSuspendProcess(handle)
        else:
            os.kill(pid, signal.SIGSTOP)
        self.suspended.append(pid)

    def end_all(self) -> None:
        for pid in self.suspended:
            if sys.platform == "win32":
                self.ntdll.NtResumeProcess(self.handles[pid])
            else:
                os.kill(pid, signal.SIGCONT)
        for pid in set(self.suspended) | set(self.find()):
            if sys.platform == "win32":
                handle = self.handles.get(pid) or self.kernel32.OpenProcess(0x0001, False, pid)
                self.kernel32.TerminateProcess(handle, 1)
                self.kernel32.CloseHandle(handle)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    def _windows_processes(self) -> dict[int, tuple[int, str]]:
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        snapshot = self.kernel32.CreateToolhelp32Snapshot(0x2, 0)
        found = {}
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
            more = self.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        self.kernel32.CloseHandle(snapshot)
        return found


def run(godot: str, addon: Path, case: str, limit: float) -> tuple[int | None, float, int, str]:
    with tempfile.TemporaryDirectory(prefix="sentry-handler-stall-", ignore_cleanup_errors=True) as scratch:
        settings = "" if case == "without the SDK" else SETTINGS
        where = clean_exit.project(Path(scratch) / "p", settings, addon)
        (where / "quit.gd").write_text(CRASH, encoding="utf-8")
        home = Path(scratch) / "user"
        env = os.environ | {"APPDATA": str(home), "XDG_DATA_HOME": str(home)}
        for name in ("DISPLAY", "WAYLAND_DISPLAY"):
            env.pop(name, None)
        log = Path(scratch) / "out.txt"
        start = time.monotonic()
        with open(log, "wb") as out:
            engine = subprocess.Popen(
                [godot, "--headless", "--verbose", "--audio-driver", "Dummy", "--path", str(where),
                 "-s", "res://quit.gd"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                **clean_exit.quiet_start())
            handlers = Handlers(engine, scratch)

            def stall() -> None:
                while engine.poll() is None and time.monotonic() - start < limit:
                    pids = handlers.find()
                    if pids:
                        while case == "once up" and UP not in log.read_bytes() and engine.poll() is None:
                            time.sleep(0.01)
                        for pid in pids:
                            handlers.suspend(pid)
                        return
                    time.sleep(0.005)

            watcher = threading.Thread(target=stall, daemon=True)
            if case in ("as it starts", "once up"):
                watcher.start()
            try:
                code = engine.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                code = None
                engine.kill()
                engine.wait()
            elapsed = time.monotonic() - start
            if watcher.is_alive():
                watcher.join()
            handlers.end_all()
        said = log.read_bytes().decode("utf-8", "replace")
        return code, elapsed, len(list(home.rglob("*.dmp"))), said


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("godot", nargs="+")
    parser.add_argument("--addon", type=Path, default=clean_exit.ADDON)
    parser.add_argument("--limit", type=float, default=150.0, help="seconds a run may take")
    asked = parser.parse_args()
    if not (asked.addon / "sentry.gdextension").is_file():
        sys.exit(f"no addon at {asked.addon}: build it first")
    failed = False
    for godot in asked.godot:
        crash_codes: set[int] = set()
        for case in CASES:
            code, elapsed, dumps, said = run(godot, asked.addon, case, asked.limit)
            shown = "hung" if code is None else f"exit {code & 0xFFFFFFFF:#x}" if sys.platform == "win32" else f"exit {code}"
            if case == "without the SDK":
                ok = code not in (None, 0)
            elif case == "never":
                ok = code not in (None, 0) and dumps > 0
            else:
                ok = code in crash_codes
            if ok and code is not None and case in ("without the SDK", "never"):
                crash_codes.add(code)
            failed |= not ok
            print(f"{'ok  ' if ok else 'FAIL'} {case}, {godot}: {shown} after {elapsed:.0f} s, {dumps} minidump(s)")
            if not ok:
                print("\n".join(f"  {line}" for line in said.splitlines()[-15:]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
