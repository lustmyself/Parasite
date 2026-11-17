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
to this script): the same src/ gives the same exe bytes on Windows (on other OSes only
Costura's metadata line endings differ). .github/workflows/builds-check.yml
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
    # Costura embeds the dependencies uncompressed: Deflate output depends on the zlib the
    # build machine's .NET uses (zlib-ng in Microsoft's builds, system zlib in distro builds),
    # which would make the exe differ between machines. See builds-check.yml.
    ("Deceive/FodyWeavers.xml", "  <Costura />", '  <Costura DisableCompression="true" />'),
    ("Deceive/Deceive.csproj",
     "    <OutputType>WinExe</OutputType>\n",
     "    <OutputType>WinExe</OutputType>\n    <AssemblyName>ParasiteOffline</AssemblyName>\n"
     "    <Product>Parasite Offline</Product>\n    <AssemblyTitle>Parasite Offline</AssemblyTitle>\n"
     "    <Company>Parasite</Company>\n"
     "    <Copyright>Copyright (c) molenzwiebel and Parasite contributors, GPL-3.0</Copyright>\n"),
]

ISSUES_URL = REPO_URL + "/issues"
# Parasite is Turkish only: what players see (chat replies from the "Parasite Active!" friend,
# message boxes) in Turkish. Applied after the patches above. The tray menu stays as it is: it is
# hidden. The chat commands (online, offline, mobile...) are commands and keep their names.
PATCHES += [
    ("Deceive/MainController.cs", '"You are now appearing online."', '"Artık çevrimiçi görünüyorsun."'),
    ("Deceive/MainController.cs", '"You are now appearing " + newStatus + "."',
     '"Artık " + (newStatus == "mobile" ? "mobilde" : "çevrimdışı") + " görünüyorsun."'),
    ("Deceive/MainController.cs", '"You are appearing online."', '"Çevrimiçi görünüyorsun."'),
    ("Deceive/MainController.cs", '"You are appearing " + Status + "."',
     '(Status == "mobile" ? "Mobilde" : "Çevrimdışı") + " görünüyorsun."'),
    ("Deceive/MainController.cs", '"Deceive is now enabled."', '"Parasite Offline açıldı."'),
    ("Deceive/MainController.cs", '"Deceive is now disabled."', '"Parasite Offline kapatıldı."'),
    ("Deceive/MainController.cs", '"Deceive is already enabled."', '"Parasite Offline zaten açık."'),
    ("Deceive/MainController.cs", '"Deceive is already disabled."', '"Parasite Offline zaten kapalı."'),
    ("Deceive/MainController.cs",
     '"You can send the following messages to quickly change Deceive settings: online/offline/mobile/enable/disable/status"',
     '"Parasite Offline\'ı hızlıca ayarlamak için şu mesajları gönderebilirsin: online/offline/mobile/enable/disable/status"'),
    ("Deceive/MainController.cs",
     '                            "Unable to connect to the chat server. Please check your internet connection. " +\n'
     '                            "If this issue persists and you can connect to chat normally without Deceive, " +\n'
     '                            "please file a bug report through GitHub (https://github.com/molenzwiebel/Deceive) or Discord.",\n',
     '                            "Sohbet sunucusuna bağlanılamadı. İnternet bağlantını kontrol et. " +\n'
     '                            "Sorun sürerse ve Parasite Offline olmadan sohbete normal bağlanabiliyorsan, " +\n'
     f'                            "lütfen GitHub\'da bildir ({ISSUES_URL}).",\n'),
    ("Deceive/ConfigProxy.cs",
     '                "Deceive was unable to rewrite a League of Legends configuration file. This normally happens because Riot changed something on their end. " +\n'
     '                "Please check if there\'s a new version of Deceive available, or contact the creator through GitHub (https://github.com/molenzwiebel/Deceive) or Discord if there\'s not.\\n\\n" +\n',
     '                "Parasite Offline bir League of Legends yapılandırma dosyasını yeniden yazamadı. Bu genellikle Riot kendi tarafında bir şeyi değiştirdiğinde olur. " +\n'
     f'                "Parasite\'ın yeni bir sürümü var mı bak; yoksa GitHub\'da bildir ({ISSUES_URL}).\\n\\n" +\n'),
    ("Deceive/StartupHandler.cs",
     '                "Deceive encountered an error and couldn\'t properly initialize itself. " +\n'
     '                "Please contact the creator through GitHub (https://github.com/molenzwiebel/Deceive) or Discord.\\n\\n" + ex,\n',
     '                "Parasite Offline bir hatayla karşılaştı ve düzgün başlatılamadı. " +\n'
     f'                "Lütfen GitHub\'da bildir ({ISSUES_URL}).\\n\\n" + ex,\n'),
    ("Deceive/StartupHandler.cs",
     '                "The Riot Client is currently running. In order to mask your online status, the Riot Client needs to be started by Deceive. " +\n'
     '                "Do you want Deceive to stop the Riot Client and games launched by it, so that it can restart with the proper configuration?",\n',
     '                "Riot Client şu anda açık. Çevrimiçi durumunu gizleyebilmek için Riot Client\'ın Parasite Offline tarafından başlatılması gerekiyor. " +\n'
     '                "Parasite Offline, Riot Client\'ı ve onun açtığı oyunları kapatıp doğru ayarlarla yeniden başlatsın mı?",\n'),
    ("Deceive/StartupHandler.cs",
     '                "Deceive was unable to find the path to the Riot Client. Usually this can be resolved by launching any Riot Games game once, then launching Deceive again. " +\n'
     '                "If this does not resolve the issue, please file a bug report through GitHub (https://github.com/molenzwiebel/Deceive) or Discord.",\n',
     '                "Parasite Offline, Riot Client\'ın yolunu bulamadı. Genellikle herhangi bir Riot Games oyununu bir kez açıp Parasite Offline\'ı yeniden başlatmak bunu çözer. " +\n'
     f'                "Çözmezse lütfen GitHub\'da bildir ({ISSUES_URL}).",\n'),
    ("Deceive/StartupHandler.cs",
     '                "Deceive was unable to obtain a necessary security certificate for intercepting and modifying the chat connection. This normally happens when there\'s " +\n'
     '                "a problem with the server that provides the certificate, but it can also be caused by network issues on your end. Please check if there\'s a new version" +\n'
     '                " of Deceive available, check your network connection, or contact the creator through GitHub (https://github.com/molenzwiebel/Deceive) or Discord.",\n',
     '                "Parasite Offline, sohbet bağlantısı için gereken güvenlik sertifikasını alamadı. Bu genellikle sertifikayı veren sunucudaki bir sorundan olur, " +\n'
     '                "ama senin ağındaki bir sorundan da olabilir. Parasite\'ın yeni bir sürümü var mı bak, internet bağlantını kontrol et" +\n'
     f'                " ya da GitHub\'da bildir ({ISSUES_URL}).",\n'),
    ("Deceive/Utils.cs",
     '"Deceive could not stop existing Riot processes because it does not have the right permissions. Please relaunch this application as an administrator and try again."',
     '"Parasite Offline, açık Riot işlemlerini kapatamadı çünkü yetkisi yok. Parasite\'ı yönetici olarak yeniden başlatıp tekrar dene."'),
    ("Deceive/Utils.cs",
     '"Your machine is failing to resolve some required domains. You will need to switch DNS servers or add an entry to your hosts file. '
     'Please see the FAQ for more information. Deceive will not work until this issue is resolved. Would you like to open the FAQ now?"',
     '"Bilgisayarın gerekli bazı alan adlarını çözümleyemiyor. DNS sunucunu değiştirmen ya da hosts dosyana bir kayıt eklemen gerekiyor. '
     'Ayrıntılar SSS sayfasında (İngilizce). Bu sorun çözülene kadar Parasite Offline çalışmaz. SSS sayfası şimdi açılsın mı?"'),
    ("Deceive/ProxiedConnection.cs", '"rosterName": "Deceive is active. Ignore any version mismatch warnings."',
     '"rosterName": "Parasite Offline açık. Sürüm uyuşmazlığı uyarılarını yok say."'),
    ("Deceive/GamePromptForm.Designer.cs", '"Which game would you like to launch?"', '"Hangi oyunu açmak istersin?"'),
    ("Deceive/GamePromptForm.Designer.cs", '"Remember my decision and skip this screen on future launches."',
     '"Seçimimi hatırla ve bu ekranı bir daha gösterme."'),
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
