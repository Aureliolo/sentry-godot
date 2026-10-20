"""Packs the Windows and Linux x86_64 builds of the addon into the fork's release assets.

    python scripts/package-desktop.py <version> [--output out]

Reads project/addons/sentry as both scons builds left it (target=editor and
target=template_release on each platform, the Linux files copied in from the machine that built
them) and writes two zips:

    sentry-godot-desktop-<version>.zip          addons/sentry/ with the libraries, the crash
                                                handler and the licence, no symbols
    sentry-godot-desktop-symbols-<version>.zip  the PDBs and split .debug files, for reading
                                                crash dumps

Entries carry a fixed time and sorted order, so the same files always give the same bytes and
the published SHA-256 can be checked against a rebuild.
"""

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "project" / "addons" / "sentry"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
EXECUTABLE = 0o100755
REGULAR = 0o100644

ADDON_FILES = [
    "sentry.gdextension",
    "bin/windows/x86_64/libsentry.windows.debug.x86_64.dll",
    "bin/windows/x86_64/libsentry.windows.release.x86_64.dll",
    "bin/windows/x86_64/crashpad_handler.exe",
    "bin/windows/x86_64/crashpad_wer.dll",
    "bin/linux/x86_64/libsentry.linux.debug.x86_64.so",
    "bin/linux/x86_64/libsentry.linux.release.x86_64.so",
    "bin/linux/x86_64/crashpad_handler",
]
SYMBOL_FILES = [
    "bin/windows/x86_64/libsentry.windows.debug.x86_64.pdb",
    "bin/windows/x86_64/libsentry.windows.release.x86_64.pdb",
    "bin/windows/x86_64/crashpad_handler.pdb",
    "bin/windows/x86_64/crashpad_wer.pdb",
    "bin/linux/x86_64/libsentry.linux.debug.x86_64.so.debug",
    "bin/linux/x86_64/libsentry.linux.release.x86_64.so.debug",
    "bin/linux/x86_64/crashpad_handler.debug",
]
# The licence sits at the repository's root; inside the addon it travels with the libraries.
EXTRA = {"LICENSE.md": ROOT / "LICENSE.md"}


def add(bundle: zipfile.ZipFile, name: str, source: Path) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    executable = source.name == "crashpad_handler"
    info.external_attr = (EXECUTABLE if executable else REGULAR) << 16
    info.create_system = 3
    bundle.writestr(info, source.read_bytes())


def pack(target: Path, entries: dict[str, Path]) -> str:
    missing = [name for name, source in entries.items() if not source.is_file()]
    if missing:
        sys.exit("missing, build it first:\n  " + "\n  ".join(missing))
    with zipfile.ZipFile(target, "w") as bundle:
        for name in sorted(entries):
            add(bundle, name, entries[name])
    return hashlib.sha256(target.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, default=ROOT / "out")
    asked = parser.parse_args()
    asked.output.mkdir(parents=True, exist_ok=True)
    prefix = "addons/sentry/"
    addon = {prefix + name: ADDON / name for name in ADDON_FILES}
    addon.update({prefix + name: source for name, source in EXTRA.items()})
    symbols = {prefix + name: ADDON / name for name in SYMBOL_FILES}
    for label, entries in (("desktop", addon), ("desktop-symbols", symbols)):
        target = asked.output / f"sentry-godot-{label}-{asked.version}.zip"
        print(f"{pack(target, entries)}  {target.name}")


if __name__ == "__main__":
    main()
