"""Packs the Windows and Linux x86_64 builds of the addon into the fork's release assets.

    python scripts/package-desktop.py <version> [--output out]

Reads project/addons/sentry as both scons builds left it (target=editor and
target=template_release on each platform, the Linux files copied in from the machine that built
them) and writes two zips:

    sentry-godot-desktop-<version>.zip          addons/sentry/ with the libraries, the crash
                                                handler, the licence and the licences of the
                                                code they carry, no symbols
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
NATIVE = ROOT / "modules" / "sentry-native"
CRASHPAD = NATIVE / "external" / "crashpad"
THIRD_PARTY_NAME = "THIRDPARTY.txt"
# What the libraries and the crash handler carry of others' code, each with the licence a game
# shipping them must reproduce. stb_sprintf is also in, as public domain, which asks for nothing.
THIRD_PARTY = [
    ("sentry-native", "MIT", "every library", NATIVE / "LICENSE"),
    ("jsmn", "MIT", "every library", NATIVE / "vendor" / "jsmn.h"),
    ("MPack", "MIT", "every library", CRASHPAD / "third_party" / "mpack" / "LICENSE"),
    ("Crashpad", "Apache-2.0", "every library and the crash handler", CRASHPAD / "LICENSE"),
    (
        "mini_chromium",
        "BSD-3-Clause",
        "every library and the crash handler",
        CRASHPAD / "third_party" / "mini_chromium" / "mini_chromium" / "LICENSE",
    ),
    ("zlib", "Zlib", "Windows", CRASHPAD / "third_party" / "zlib" / "zlib" / "LICENSE"),
    (
        "getopt",
        "public domain, credit asked",
        "Windows",
        CRASHPAD / "third_party" / "getopt" / "LICENSE",
    ),
    ("libunwind", "MIT", "Linux", NATIVE / "vendor" / "libunwind" / "COPYING"),
    (
        "Linux Syscall Support",
        "BSD-3-Clause",
        "Linux",
        CRASHPAD / "third_party" / "lss" / "lss" / "LICENSE",
    ),
]


def licence_text(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".h":
        # A header's licence is its first comment.
        text = text[text.index("/*") + 2 : text.index("*/")]
        text = "\n".join(line.strip().removeprefix("*").strip() for line in text.splitlines())
    return text.strip()


def third_party() -> bytes:
    parts = [
        "Others' code in Sentry's Godot SDK as this fork builds it for Windows and Linux x86_64,"
        " with the licence each is under. Sentry's Godot SDK itself is in LICENSE.md."
    ]
    for name, licence, where, source in THIRD_PARTY:
        rule = "=" * 78
        parts.append(f"{rule}\n{name} ({licence}), in {where}\n{rule}\n\n{licence_text(source)}")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def add(bundle: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    executable = name.endswith("/crashpad_handler")
    info.external_attr = (EXECUTABLE if executable else REGULAR) << 16
    info.create_system = 3
    bundle.writestr(info, data)


def pack(target: Path, entries: dict[str, Path], written: dict[str, bytes]) -> str:
    missing = [name for name, source in entries.items() if not source.is_file()]
    if missing:
        sys.exit("missing, build it first:\n  " + "\n  ".join(missing))
    contents = {name: source.read_bytes() for name, source in entries.items()} | written
    with zipfile.ZipFile(target, "w") as bundle:
        for name in sorted(contents):
            add(bundle, name, contents[name])
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
    notices = {prefix + THIRD_PARTY_NAME: third_party()}
    for label, entries, written in (
        ("desktop", addon, notices),
        ("desktop-symbols", symbols, {}),
    ):
        target = asked.output / f"sentry-godot-{label}-{asked.version}.zip"
        print(f"{pack(target, entries, written)}  {target.name}")


if __name__ == "__main__":
    main()
