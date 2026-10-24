"""Checks that a project carrying the addon exits cleanly under each Godot given.

    python scripts/check-clean-exit.py <godot> [<godot> ...] [--runs 3] [--addon <dir>]

Copies project/addons/sentry, as the builds left it (or the addons/sentry folder --addon names,
an unpacked release for one), into a project of its own in a temporary
folder, holding nothing but a script that quits, and runs it headless with each Godot, with the
SDK left uninitialised as every game starts it and again with it initialised. A run passes when
it exits 0 and prints no leaked instance. Godot 4.8 destroys a bound method's default values only
after ObjectDB is gone, so an Object among them crashes every exit (SIGSEGV on Linux, an access
violation on Windows) where Godot 4.7 exits cleanly.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "project" / "addons" / "sentry"
QUIT = 'extends SceneTree\n\n\nfunc _initialize() -> void:\n\tprint("quit.gd up")\n\tquit()\n'
# The DSN points nowhere that answers, so an initialised SDK starts and sends nothing.
CASES = {
    "uninitialised": "",
    "initialised": '\n[sentry]\n\noptions/dsn="https://public@127.0.0.1:9/1"\n',
}
CLEAN = "quit.gd up"


def project(where: Path, settings: str, addon: Path) -> Path:
    where.mkdir(parents=True)
    (where / "project.godot").write_text(
        f'config_version=5\n\n[application]\n\nconfig/name="sentry-clean-exit"\n{settings}',
        encoding="utf-8",
    )
    (where / "quit.gd").write_text(QUIT, encoding="utf-8")
    shutil.copytree(addon, where / "addons" / "sentry")
    (where / ".godot").mkdir()
    (where / ".godot" / "extension_list.cfg").write_text(
        "res://addons/sentry/sentry.gdextension\n", encoding="utf-8"
    )
    return where


def run(godot: str, where: Path) -> tuple[int, str]:
    # The user folder, where an initialised SDK keeps what it could not send, stays in the scratch folder.
    home = where.parent / "user"
    env = os.environ | {"APPDATA": str(home), "XDG_DATA_HOME": str(home)}
    command = [godot, "--headless", "--verbose", "--audio-driver", "Dummy", "--path", str(where)]
    done = subprocess.run(
        [*command, "-s", "res://quit.gd"],
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return done.returncode, done.stdout + done.stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("godot", nargs="+")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--addon", type=Path, default=ADDON)
    asked = parser.parse_args()
    if not (asked.addon / "sentry.gdextension").is_file():
        sys.exit(f"no addon at {asked.addon}: build it first")
    failed = False
    with tempfile.TemporaryDirectory(prefix="sentry-clean-exit-") as scratch:
        for case, settings in CASES.items():
            where = project(Path(scratch) / case, settings, asked.addon)
            for godot in asked.godot:
                for _ in range(asked.runs):
                    code, said = run(godot, where)
                    leaked = [line for line in said.splitlines() if "leaked" in line.lower()]
                    if code != 0 or leaked or CLEAN not in said:
                        failed = True
                        print(f"FAIL {case} {godot}: exit {code}")
                        for line in leaked or said.splitlines()[-15:]:
                            print(f"  {line}")
                        break
                else:
                    print(f"ok   {case} {godot}: {asked.runs} clean exits")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
