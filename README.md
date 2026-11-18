<div align="center">

# 💜 Parasite

<img src="./assets/icon.png" alt="Parasite" width="112" height="112">

**Every League of Legends skin, right from champion select.**

[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/lustmyself/Parasite/releases/latest) [![Downloads](https://img.shields.io/github/downloads/lustmyself/Parasite/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/lustmyself/Parasite/releases/latest) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE)

</div>

> [!CAUTION]
> Parasite is only distributed through [GitHub Releases](https://github.com/lustmyself/Parasite/releases/latest).

Parasite is a free, open-source skin changer. It sits in the system tray, adds its menus to the League client, and applies the skin you hover in champion select when the game loads. Only you see the skin (and other Parasite users in your lobby), and gameplay doesn't change: Parasite gives **no competitive advantage**.

## Features

- **Every skin, chroma and form**, picked straight from champion select
- **Custom mods**: skins, maps, fonts, announcers and more (`.fantome`, `.zip`, `.modpkg`)
- **Desktop hub**: startup progress, updates, your Riot ID, rank, last match and your server's
  Grandmaster and Challenger LP cutoffs, quick actions and Parasite Offline's status
- **Parasite Offline**: appear offline or on mobile to your friends while you play
- **Custom skins tab**: drop your own `.fantome`, `.zip` or `.modpkg` skins in and switch them
  on per champion; they play on the champion's default skin
- **Spotify themes**: 22 Spicetify themes for the Spotify desktop app, re-applied after
  Spotify updates
- **Silent updates**: new versions download in the background and install while League is closed
- **Lobby Reveal**: your teammates' names and op.gg links in champion select
- **Skin sharing**: Parasite users in your lobby or champ select team see each other's skins and
  profile icons, through Parasite's own relay (`parasite/relay`)
- **Random and Historic** skin picks, and the skin's name on the loading screen
- **Turkish**: the hub, the client menus, the installer and Parasite Offline
- **Free**: if you paid for Parasite, you got scammed 💀

## Install

1. Install **[LTK Manager](https://github.com/LeagueToolkit/ltk-manager/releases)**, which Parasite applies skins through. You never have to open it.
2. Download and run the [**latest Parasite installer**](https://github.com/lustmyself/Parasite/releases/latest).
3. Start Parasite, then hover a skin in champion select.

Parasite needs Windows 10 or 11 and updates itself.

## FAQ

<details>
<summary><b>How does it work?</b></summary>

<br>

Parasite loads its plugins into the League client with [Pengu Loader](https://github.com/PenguLoader/PenguLoader). Just before the champion select countdown ends, it locks in the skin you hover and has LTK Manager patch it into the game. The point where it locks in is the **Injection Threshold** (1 to 2 seconds, in Settings): a change after it is ignored. See [Architecture](CONTRIBUTING.md#architecture) for the full picture.

</details>

<details>
<summary><b>Do I need to open LTK Manager?</b></summary>

<br>

No. Parasite starts it in the background and closes it after the game. Leave it closed: if it is already open when a game starts, Parasite skips the skin and asks you to close it. Your own LTK Manager mods are paused for the game and turned back on after.

If Parasite can't find LTK Manager, click **Set up path** at startup and select `ltk-manager.exe`.

</details>

<details>
<summary><b>Parasite doesn't show up in the client, or skins don't load</b></summary>

<br>

Open the **Troubleshooting** panel in Parasite's settings, or right-click the tray icon and choose **Diagnose Parasite startup**. See [docs/troubleshooting.md](docs/troubleshooting.md) for the diagnostic report and for recovering an interrupted update, and open an [issue](https://github.com/lustmyself/Parasite/issues/new/choose) if you're stuck.

</details>

<details>
<summary><b>Does Parasite collect data?</b></summary>

<br>

No. Parasite sends no usage data anywhere: the analytics Rose has are switched off. It talks to GitHub (updates, skins), the League client on your PC, and replays.lol for the LP cutoffs on the welcome card.

</details>

## Contributing

Bug reports, translations and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers how to contribute, then [how Parasite works](CONTRIBUTING.md#architecture).

## Credits

[Pengu Loader](https://github.com/PenguLoader/PenguLoader) (vendored and built with Parasite, see its [license](https://github.com/PenguLoader/PenguLoader/blob/main/LICENSE)) · [LTK Manager](https://github.com/LeagueToolkit/ltk-manager) · [CommunityDragon](https://github.com/CommunityDragon/Data)

Parasite is built on [Rose](https://github.com/Alban1911/Rose) (MIT). Its client theme comes from
[Elaina](https://github.com/Elaina69/Elaina-theme) (MIT) and Parasite Offline from
[Deceive](https://github.com/molenzwiebel/Deceive) (GPL-3.0).

## Legal

Parasite is not endorsed by or affiliated with Riot Games. Riot Games and all related properties are trademarks or registered trademarks of Riot Games, Inc. Riot Games does not allow custom skins that reproduce its real skins, which is what Parasite does. Use Parasite at your own risk: its developers are not responsible for any consequence, including account suspensions or bans.

<div align="center">
<br>

**Parasite** · *League, unlocked.*

</div>
