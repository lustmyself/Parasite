# 💜 Parasite - Effortless Skin Changer for LoL

<div align="center">

  <img src="./assets/icon.png" alt="Parasite Icon" width="128" height="128">

[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/lustmyself/Parasite/releases/latest) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE) [![Downloads](https://img.shields.io/github/downloads/lustmyself/Parasite/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/lustmyself/Parasite/releases/latest)


</div>

> [!CAUTION]
> The `parasiteskin.xyz` website is **UNRELATED** to this project and does not represent this project. **THE DOWNLOAD ON THAT SITE CONTAINS MALWARE**. If you downloaded anything from `parasiteskin.xyz`, reinstall your PC. The only official download is the [GitHub releases page](https://github.com/lustmyself/Parasite/releases/latest).

---

## Overview

Parasite is an open-source automatic skin changer for League of Legends that enables seamless access to all skins in the game. The application runs silently in the system tray and automatically detects skin selections during champion select, injecting the chosen skin when the game loads.

Built on the [Pengu Loader](https://github.com/PenguLoader/PenguLoader) framework, Parasite integrates JavaScript extensions into the League Client to enable modular UI interactions. It strictly modifies local rendering variables to display custom models and textures. It is designed purely as an exploration of client-side asset management, providing no manipulation of network data, memory states, or gameplay mechanics, thereby **offering zero competitive advantage**.

## Architecture

Parasite consists of three main components:

### Python Backend

- **LCU API Integration**: Communicates with the League Client via the League Client Update (LCU) API
- **Skin Injection**: Handles skin injection compatible with Riot Vanguard
- **WebSocket Bridge**: Operates a WebSocket server for real-time communication with frontend plugins
- **Skin Management**: Downloads and manages skin files from the [LeagueSkins repository](https://github.com/Alban1911/LeagueSkins)
- **Skin sharing**: Parasite users in the same lobby or team see each other's skins and icons
- **Game Monitoring**: Tracks game state, champion select phases, and loadout countdowns
- **Auto-Updater**: Checks GitHub for new releases and prompts users to install updates
- **Analytics**: Sends a startup ping, a 15-minute presence heartbeat, and a best-effort close ping (configurable, runs in a background thread)

### Privacy

Parasite sends no usage data anywhere: the analytics Rose has are switched off.
It talks to GitHub (updates, skins), the League client on your PC, and replays.lol for
the LP cutoffs on the welcome card.

<!-- Rose's party relay server is not part of Parasite -->

### Pengu Loader Plugins

Parasite includes a suite of JavaScript plugins that extend the League Client UI:

- **PARASITE-UI**: Unlocks locked skin previews in champion select, enabling hover interactions on all skins
- **PARASITE-SkinMonitor**: Monitors currently selected skin's name and sends it to the Python backend via WebSocket. It also hosts the bridge the other plugins use to talk to Parasite
- **PARASITE-CustomSkinSelector**: Lists the custom skin mods made for the hovered skin and applies the one you pick
- **PARASITE-CustomWheel**: Custom mods panel for maps, fonts, announcers and other mods
- **PARASITE-ChromaWheel**: Enhanced chroma selection interface for choosing any chroma variant
- **PARASITE-FormsWheel**: Custom form selection interface for skins with multiple forms (Elementalist Lux, Sahn Uzal Mordekaiser, Spirit Blossom Morgana, Radiant Sett)
- **PARASITE-SettingsPanel**: Settings panel accessible from the League of Legends Client
- **PARASITE-RandomSkin**: Random skin selection feature
- **PARASITE-HistoricMode**: Access to the last used skin for every champion
- **PARASITE-PartyMode**: Party mode UI — displays a panel in lobby and champion select to enable skin sharing, view connected peers, and see friends' skin selections in real time
- **PARASITE-I18n**: Translates Parasite's menus into the language picked in Settings, else the League client's
- **PARASITE-Jade**: Client customization — regalia borders, backgrounds, banners, icons, titles, and win/loss stats (shipped disabled)

## How It Works

1. **League Client Integration**: Parasite activates **[Pengu Loader](https://github.com/PenguLoader/PenguLoader)** on startup, which injects the JavaScript plugins into the League Client. If the client is already open, Parasite restarts it so the plugins load (during champion select, the restart waits for the lobby or the end of the game)
2. **Skin Detection**: When you hover over a skin in champion select, `PARASITE-SkinMonitor` detects the selection and sends it to the Python backend
3. **Game Opening Delay**: To give the injection time to happen, Parasite suspends the game process until the overlay is ready. If Parasite closes during that window, it resumes the game the next time it starts
4. **Game Injection**: Parasite injects the selected skin when the game starts
5. **Seamless Experience**: The skin loads as if you owned it, with full chroma support and no gameplay impact (Parasite will **never** provide any competitive advantage to its users)

## Features

- **Smart Injection**: Never injects skins you already own
- **Custom Mods**: Custom skins, maps, fonts and announcers (`.fantome`, `.zip` and `.modpkg`)
- **Desktop hub**: Startup progress, updates, your Riot ID, rank, last match and your server's
  Grandmaster and Challenger LP cutoffs, quick actions and Parasite Offline's status
- **Parasite Offline**: Appear offline or on mobile to your friends while you play
- **Custom skins tab**: Drop your own `.fantome`, `.zip` or `.modpkg` skins in and switch them
  on per champion; they play on the champion's default skin
- **Spotify themes**: 22 Spicetify themes for the Spotify desktop app, re-applied after
  Spotify updates
- **Silent updates**: New versions download in the background and install while League is closed
- **Lobby Reveal**: Your teammates' names and op.gg links in champion select
- **Skin sharing**: Parasite users in your lobby or champ select team see each other's skins and
  profile icons, through Parasite's own relay (`parasite/relay`)
- **Loading Screen Name**: The loading screen shows the injected skin's name; the chat and the name over your champion keep the champion's
- **Multi-Language Support**: Works with any client language, with Parasite's menus in 22 languages
- **Open Source**: Fully open source and extensible
- **Free**: If you bought this software, you got scammed 💀

## Requirements

- **Windows 10/11**
- **League of Legends** installed
- **LTK Manager** - the app Parasite applies skins through; Parasite finds it on its own (see below)

### LTK Manager Requirement

Parasite applies skins through LTK Manager, which it drives over the bridge it
builds from `native/ltf/` (`ltk_launcher.exe` + `LeagueToolFlop.dll`). Install
LTK Manager once and Parasite finds it: a path set as `ltkManagerPath` in
`cf.ini` wins, then a running instance, then the known install locations.

If Parasite can't find LTK Manager, it says so at startup: install it, or click
**Set up path** and select its `ltk-manager.exe` (Parasite saves it as
`ltkManagerPath` and starts). You never have to open LTK Manager yourself:
Parasite starts it in the background during champ select and closes it after the
game. A running LTK Manager is left alone: Parasite only closes the instance it
started itself. The bridge can only load into an LTK Manager Parasite starts, so if
yours is already open when a game starts, Parasite skips the injection and asks you
in Troubleshooting to close it (also from the system tray).

For each game Parasite turns off the mods you enabled in LTK Manager, so only the
selected skin is patched in, and turns them back on afterwards. LTK Manager's
patcher only applies to a game started after it began scanning, so Parasite
installs the skin you select while the champ select countdown runs. The skin
selected at the injection threshold (1 to 2 seconds before the countdown ends,
in Settings) is the one applied: a change after it is ignored, so you keep that
skin instead of getting the default one.

## Installation

1. Download the latest installer from [Releases](https://github.com/lustmyself/Parasite/releases/latest)
2. Run the installer as Administrator
3. Launch Parasite from the Start Menu or desktop shortcut

## Diagnose startup problems

If Parasite is missing from the League client or game skins do not load, reproduce
the problem, leave Parasite and League open, then right-click Parasite's system tray icon
and choose **Diagnose Parasite startup**. A progress window immediately confirms the
run started, with an animated loading bar and elapsed time. **Run in background**
hides the window while collection continues. The window shows completion or a
failure, and the report folder opens when finished. **Open Logs folder** opens
Parasite's `logs` folder, including the `diagnostics` subfolder for past runs.

Reports live in `logs\diagnostics\Parasite-Diagnostics-<timestamp>-<id>` under Parasite's
user data folder (normally `%LOCALAPPDATA%\Parasite`), separate from the ordinary log
files. Each run includes `report.txt`, `report.json`, and `collector-status.txt`.
If collection is blocked or times out after three minutes, the status explains
the failure and any partial reports are marked incomplete.

The bundled Windows PowerShell 5.1 collector checks Windows/runtime differences,
Pengu configuration and activation, patcher files, relevant security events,
process privileges, bridge connectivity, and selected recent error excerpts.
It reads system state without applying repairs, restarting League, or changing
security settings. A clock check contacts `time.windows.com`; reports are never
uploaded. Common credentials and profile paths are redacted, but review reports
before sharing them with support. `UNKNOWN` means a check was unavailable, and
a warning is a possible cause rather than proof of failed injection.

For manual collection, run `assets\diagnostics\Diagnose-Parasite.ps1`; its optional
`-SkipNetworkChecks` flag skips the external clock comparison. No Python or
PowerShell 7 installation is needed in packaged Parasite.

## Building from source

Parasite builds the Pengu Loader executable from the vendored source in
`vendor/PenguLoader-1.1.6/` as part of the normal Parasite build. You do not need
to download or commit a prebuilt `Pengu Loader.exe`.

### Prerequisites

- Windows 10/11
- Python 3.11 or newer
- Visual Studio Build Tools with the .NET desktop build tools, WPF support,
  and the .NET Framework 4.7.2 targeting pack (for Pengu Loader), and the
  MSVC C++ build tools with the C++20 workload (for the LTF bridge in
  `native/ltf/`)
- Inno Setup 6 if you also want to create the installer

Clone the repository and enter its directory:

```powershell
git clone https://github.com/lustmyself/Parasite.git
cd Parasite
```

Install the Python dependencies first:

```powershell
python -m pip install -r requirements.txt
```

Build the loader by itself, if needed:

```powershell
python scripts/build_pengu_loader.py
```

Build Parasite (rebuilds the loader and the LTF bridge):

```powershell
python scripts/build_pyinstaller.py
```

The packaged application is written to `dist/Parasite/`. To build both Parasite and
the Windows installer in one step:

```powershell
python scripts/build_all.py
```

The installer is written to `installer/Parasite_Setup_<version>.exe`. Use
`scripts/build_pyinstaller.py` or `scripts/build_all.py` instead of invoking
`pyinstaller Parasite.spec` directly, because the Parasite build scripts compile
Pengu Loader first.

To create the update package the auto-updater downloads from a release
(`installer/update_package_<version>.zip`, `hashes.game.txt` excluded):

```powershell
python scripts/create_update_package.py
```

## Credits

Parasite uses the [official Pengu Loader](https://github.com/PenguLoader/PenguLoader)
project. Its source is vendored and built as part of Parasite, with Parasite-specific
lifecycle integration added around the loader. Please see the
[official Pengu Loader license](https://github.com/PenguLoader/PenguLoader/blob/main/LICENSE)
and credit the Pengu Loader contributors.

## Contributing

Contributions are welcome. Report bugs and suggest features through the
[issue forms](https://github.com/lustmyself/Parasite/issues/new/choose); installation
questions are welcome there too.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the tests and
checks that CI runs on every pull request, and the project structure.

## Legal Disclaimer

This project is not endorsed by or affiliated with Riot Games. Riot Games and all related properties are trademarks or registered trademarks of Riot Games, Inc.

Riot Games does not allow custom skins that reproduce its real skins, which is what Parasite does. Use Parasite at your own risk: its developers are not responsible for any consequence of using it, including account suspensions or bans.

## Support

Found a bug or have an idea? Open an [issue](https://github.com/lustmyself/Parasite/issues/new/choose).

---

**Parasite** - _League, unlocked._
