"""Build Parasite Offline from a Deceive checkout.

Usage:
    python parasite/offline/build_offline.py path/to/Deceive     # regenerate src/, then build
    python parasite/offline/build_offline.py --source-only path/to/Deceive
    python parasite/offline/build_offline.py --build-only        # build the committed src/

Deceive (github.com/molenzwiebel/Deceive, GPL-3.0) proxies Riot chat so you can
appear offline. This script copies its source into parasite/offline/src, renames
everything users see to Parasite, removes the first-launch messages (chat welcome,
tray balloon, update prompt), builds it with `dotnet build` and puts the exe in
parasite/overlay/injection/tools/ParasiteOffline.exe. The modified source stays in the
repo because the GPL requires it to ship with the binary.

The build is deterministic (Directory.Build.props, global.json, packages.lock.json next
to this script): the same src/ gives the same exe bytes. .github/workflows/builds-check.yml
rebuilds the exe on Windows with --build-only and fails if it differs from the committed one.
Text files in src/ are written with LF line endings on every OS (see .gitattributes).
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OFFLINE = ROOT / "parasite" / "offline"
SRC = OFFLINE / "src"
EXE = ROOT / "parasite" / "overlay" / "injection" / "tools" / "ParasiteOffline.exe"
ICON = ROOT / "parasite" / "overlay" / "assets" / "icon.ico"
REPO_URL = "https://github.com/lustmyself/Parasite"
TEXT_SUFFIXES = {".cs", ".csproj", ".sln", ".xml", ".xsd", ".resx", ".manifest", ".md", ".json", ".config", ""}

# (file, old, new): exact replacements in Deceive's source. Each must match.
PATCHES = [
    # No welcome messages in chat on the first launch.
    ("Deceive/MainController.cs",
     "if (!SentIntroductionText && !Persistence.GetHasShownIntroduction())",
     "if (false)"),
    # No "masking your status" balloon when it starts.
    ("Deceive/MainController.cs", "        TrayIcon.ShowBalloonTip(5000);\n", ""),
    # No tray icon of its own: Parasite's tray menu and the CUSTOMIZE tab set the status.
    ("Deceive/MainController.cs", "            Visible = true,\n", "            Visible = false,\n"),
    # The status file keeps the status in use, not only the one at exit: Parasite's hub reads it
    ("Deceive/MainController.cs",
     "    private async Task UpdateStatusAsync(string newStatus)\n    {\n",
     "    private async Task UpdateStatusAsync(string newStatus)\n    {\n"
     "        try { File.WriteAllText(StatusFile, newStatus); } catch (IOException) { }\n"),
    # Parasite ships updates itself; no prompt to download Deceive.
    ("Deceive/StartupHandler.cs", "        _ = Utils.CheckForUpdatesAsync();\n", ""),
    ("Deceive/StartupHandler.cs",
     'public static string DeceiveTitle => "Deceive " + Utils.DeceiveVersion;',
     'public static string DeceiveTitle => "Parasite Offline";'),
    # Its own settings folder, apart from Parasite's.
    ("Deceive/Persistence.cs",
     'Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Deceive")',
     'Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Parasite Offline")'),
    # Parasite has no FAQ of its own: the DNS fix lives in Deceive's.
    ("Deceive/Utils.cs", "Please see the Deceive FAQ for more information.",
     "Please see the FAQ for more information."),
    ("Deceive/Utils.cs", 'Process.Start("https://github.com/molenzwiebel/Deceive#FAQ");',
     'Process.Start("https://github.com/molenzwiebel/Deceive#faq");'),
    ("Deceive/Deceive.csproj",
     "    <OutputType>WinExe</OutputType>\n",
     "    <OutputType>WinExe</OutputType>\n    <AssemblyName>ParasiteOffline</AssemblyName>\n"
     "    <Product>Parasite Offline</Product>\n    <AssemblyTitle>Parasite Offline</AssemblyTitle>\n"
     "    <Company>Parasite</Company>\n"
     "    <Copyright>Copyright (c) molenzwiebel and Parasite contributors, GPL-3.0</Copyright>\n"),
]

STRING_LITERAL = re.compile(r'\$?"(?:[^"\\\n]|\\.)*"')
# The word alone, so names inside interpolations ({DeceiveTitle}) keep working.
WORD = re.compile(r"\bDeceive\b")
# Resource lookups use the namespace inside a string; leave those alone.
SKIP_RENAME = {"Deceive/Properties/Resources.Designer.cs"}


def rename_strings(text):
    # Links to Deceive's repo point at Parasite's, except its FAQ section
    text = re.sub(r"https://github\.com/molenzwiebel/Deceive(?!#faq)", REPO_URL, text)
    return STRING_LITERAL.sub(
        lambda m: m.group(0) if "molenzwiebel/Deceive#faq" in m.group(0) else WORD.sub("Parasite", m.group(0)),
        text)


def write_lf(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def normalize_line_endings():
    """CRLF -> LF in every text file under src/, so a checkout with core.autocrlf (Windows)
    regenerates the same bytes as one without."""
    for path in SRC.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            data = path.read_bytes()
            if b"\r\n" in data:
                path.write_bytes(data.replace(b"\r\n", b"\n"))


def generate(upstream):
    if SRC.exists():
        shutil.rmtree(SRC)
    shutil.copytree(upstream / "Deceive", SRC / "Deceive",
                    ignore=shutil.ignore_patterns("bin", "obj"))
    for name in ("Deceive.sln", "LICENSE", "README.md"):
        shutil.copy2(upstream / name, SRC / name)
    normalize_line_endings()

    for rel, old, new in PATCHES:
        path = SRC / rel
        text = path.read_text(encoding="utf-8-sig")
        if old not in text:
            sys.exit(f"[offline] patch target not found in {rel}: {old[:70]!r}")
        write_lf(path, text.replace(old, new))

    for path in (SRC / "Deceive").rglob("*.cs"):
        rel = path.relative_to(SRC).as_posix()
        if rel in SKIP_RENAME:
            continue
        text = path.read_text(encoding="utf-8-sig")
        renamed = rename_strings(text)
        if renamed != text:
            write_lf(path, renamed)
        leftover = [m.group(0) for m in STRING_LITERAL.finditer(renamed)
                    if WORD.search(m.group(0).replace("molenzwiebel/Deceive#faq", ""))]
        if leftover:
            sys.exit(f"[offline] Deceive left in {rel}: {leftover[:3]}")

    shutil.copy2(ICON, SRC / "Deceive" / "Resources" / "deceive.ico")
    print(f"[offline] {SRC.relative_to(ROOT)} generated from {upstream}")


def build(locked):
    project = SRC / "Deceive" / "Deceive.csproj"
    for leftover in ("bin", "obj"):
        shutil.rmtree(SRC / "Deceive" / leftover, ignore_errors=True)
    # cwd=OFFLINE so dotnet finds global.json (the pinned SDK).
    restore = ["dotnet", "restore", str(project), "-nologo"]
    restore += ["--locked-mode"] if locked else ["--force-evaluate"]
    subprocess.run(restore, check=True, cwd=OFFLINE)
    subprocess.run(["dotnet", "build", str(project), "-c", "Release", "--no-restore",
                    "-nologo", "-v", "q"], check=True, cwd=OFFLINE)
    built = SRC / "Deceive" / "bin" / "Release" / "net472" / "ParasiteOffline.exe"
    EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built, EXE)
    shutil.rmtree(SRC / "Deceive" / "bin")
    shutil.rmtree(SRC / "Deceive" / "obj")
    print(f"[offline] {EXE.relative_to(ROOT)} built from {SRC.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--source-only", action="store_true", help="regenerate src/ without building")
    mode.add_argument("--build-only", action="store_true",
                      help="build the committed src/ with the locked packages (what CI checks)")
    parser.add_argument("deceive", nargs="?", type=Path, help="Deceive checkout (not with --build-only)")
    args = parser.parse_args()
    if args.build_only == (args.deceive is not None):
        parser.error("give a Deceive checkout, or --build-only without one")

    if not args.build_only:
        generate(args.deceive)
    if not args.source_only:
        # A fresh Deceive may change the packages: refresh the lock file then; otherwise
        # the build must use exactly the locked packages.
        build(locked=args.build_only)


if __name__ == "__main__":
    main()
