"""Build the PARASITE-Theme Pengu plugin from an Elaina theme release.

Usage:
    python parasite/theme/build_theme.py ElainaV4.zip elaina-theme-data-X.Y.Z.tgz

ElainaV4.zip is the release asset from github.com/Elaina69/Elaina-theme and the
.tgz is the matching `elaina-theme-data` package from npm (both MIT). The output
replaces parasite/overlay/Pengu Loader/plugins/PARASITE-Theme, which sync.py then copies
into the tree like any other overlay file.

What changes compared to Elaina:
- Every "Elaina" name becomes "Parasite" (code, storage keys, CSS, locales, files).
- The data module the theme loads from jsdelivr at every start is replaced by
  parasite/theme/data, shipped inside the plugin: no remote code, no tracking,
  no cloud backup or icon upload to Elaina's server.
- Elaina/anime artwork, the bundled songs, contributor photos, donation links,
  custom champion art and fonts we can't redistribute are removed or replaced
  with Parasite's Kai'Sa artwork.
- Settings that broadcast fake rank/mastery to friends start disabled.
"""

import re
import shutil
import sys
import tarfile
import tempfile
import wave
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "parasite" / "overlay" / "Pengu Loader" / "plugins" / "PARASITE-Theme"
BRAND = ROOT / "parasite" / "overlay" / "assets"
REPO_URL = "https://github.com/lustmyself/Parasite"

TEXT_SUFFIXES = {".js", ".css", ".txt", ".json", ".md", ".url"}

# Files dropped from the release (relative to the plugin root).
REMOVE = [
    # The update popup's styles, no longer loaded (their bare .message rule hid champ select's text)
    "assets/styles/themes/theme-update-message.css",
    "assets/backgrounds/audio/Laur - Mellifluous.flac",
    "assets/backgrounds/audio/Laur - その花は世界を紡ぐ.flac",
    "assets/backgrounds/wallpapers/elaina1.webm",
    "assets/backgrounds/wallpapers/elaina2.jpg",
    "assets/champs",
    "assets/icon/about-us",
    "assets/icon/avatar.gif",
    "assets/icon/loading.gif",
    "assets/icon/animation-logo.gif",
    "assets/icon/ko-fi.webp",
    "assets/icon/paypal.png",
    "assets/icon/momo.svg",
    "assets/fonts/elaina-herculanum_roman.ttf",
    "assets/fonts/aegirseaborn.ttf",
    "assets/fonts/minecraftregular-bmg3.otf",
]

ABOUT_US = '''async function aboutustab(panel) {
  panel.prepend(
    UI.createRow("", [
      UI.createRow("Developer", [
        UI.createRow("dev-avatar", [
          UI.createRow("dev-div", [
            UI.createImageWithLink(true, "logo.png", "dev_ava", "%s", () => {
            }),
            UI.createLabel("Parasite", "first_line_elaina"),
            UI.createLabel("github.com/lustmyself/Parasite", "")
          ])
        ])
      ])
    ])
  );
}

''' % REPO_URL

ADD_WALLPAPER_JS = '''    const addBg = this.createElementWithId("div", "add-bg");
    addBg.textContent = "+";
    addBg.title = parasiteTr("Add wallpaper");
    // Parasite: + opens the wallpapers folder and watches it; a file copied in shows up
    // in the list and becomes the wallpaper, no file name to type
    const addBgName = this.createElementWithId("div", "add-bg-name");
    addBgName.hidden = true;
    wallpaperControls.append(addBg, addBgName);
    const addOption = (name) => {
      const option = document.createElement("lol-uikit-dropdown-option");
      option.setAttribute("slot", "lol-uikit-dropdown-option");
      option.innerText = name;
      option.onclick = async () => {
        document.getElementById("elaina-bg").classList.add("webm-hidden");
        document.getElementById("elaina-static-bg").classList.add("webm-hidden");
        ElainaData.set("wallpaper-index", ElainaData.get("Wallpaper-list").indexOf(name));
        await wallpaperController.changeBG(name);
      };
      bgDropdown.appendChild(option);
    };
    const useWallpaper = async (name) => {
      bgDropdown.querySelectorAll("lol-uikit-dropdown-option").forEach((option) => {
        option.toggleAttribute("selected", option.innerText === name);
      });
      document.getElementById("elaina-bg").classList.add("webm-hidden");
      document.getElementById("elaina-static-bg").classList.add("webm-hidden");
      ElainaData.set("wallpaper-index", ElainaData.get("Wallpaper-list").indexOf(name));
      await wallpaperController.changeBG(name);
    };
    let watching = null;
    addBg.addEventListener("click", async () => {
      const first = await parasiteAssets("wallpaper", "list");
      if (first.error) {
        addBgName.textContent = first.error;
        addBgName.hidden = false;
        return;
      }
      parasiteAssets("wallpaper", "open");
      const known = new Set(first.files || []);
      // Files already in the folder but not in the list yet (copied in before) are added too
      for (const name of first.files || []) {
        const list = ElainaData.get("Wallpaper-list") || [];
        if (!list.includes(name)) {
          ElainaData.set("Wallpaper-list", [...list, name]);
          addOption(name);
        }
      }
      addBgName.textContent = parasiteTr("Copy your picture or video into the folder that opened");
      addBgName.hidden = false;
      clearInterval(watching);
      const until = Date.now() + 3 * 60 * 1000;
      watching = setInterval(async () => {
        if (Date.now() > until) {
          clearInterval(watching);
          addBgName.hidden = true;
          return;
        }
        const reply = await parasiteAssets("wallpaper", "list");
        const added = (reply.files || []).filter((name) => !known.has(name));
        if (!added.length) return;
        clearInterval(watching);
        const list = ElainaData.get("Wallpaper-list") || [];
        for (const name of added) {
          if (!list.includes(name)) {
            list.push(name);
            addOption(name);
          }
        }
        ElainaData.set("Wallpaper-list", list);
        await useWallpaper(added[added.length - 1]);
        addBgName.textContent = parasiteTr("{name} is your wallpaper", { name: added[added.length - 1] });
        setTimeout(() => { addBgName.hidden = true; }, 4000);
      }, 2000);
    });
'''

ADD_WALLPAPER_CSS = '''/* Parasite: the profile page shows only the profile background, not the wallpaper
   and not League's own client background either */
html.parasite-profile-page #parasite-bg,
html.parasite-profile-page #parasite-static-bg,
html.parasite-profile-page #background-ambient {
    opacity: 0 !important;
}

#add-bg {
    position: relative !important;
    width: 21px !important;
    height: 21px !important;
    margin-left: 7px;
    margin-top: 11px;
    border: 2px solid #8c8263 !important;
    border-radius: 50% !important;
    background-color: black !important;
    color: #cdbe91;
    font: bold 17px/21px sans-serif;
    text-align: center;
    cursor: pointer;
    pointer-events: auto;
}

#add-bg:hover {
    color: #f0e6d2;
    border-color: #c8aa6e !important;
}

#add-bg-name {
    width: auto;
    height: 23px;
    line-height: 23px;
    white-space: nowrap;
    margin-left: 7px;
    margin-top: 10px;
    padding: 0 6px;
    background: #010a13e6;
    border: 1px solid #785a28;
    color: #f0e6d2;
    font-size: 12px;
    pointer-events: auto;
}

#add-bg-name[hidden] {
    display: none;
}

#bg-size-hint {
    margin-top: 4px;
    color: #a09b8c;
    font-size: 11px;
    letter-spacing: 0.5px;
}

'''

PARASITE_PANEL_JS = '''// Turkish for Parasite's own texts in the panel; other languages go through PARASITE-I18n
const PARASITE_TR = {
  "CUSTOMIZE": "ÖZELLEŞTİR",
  "Status": "Durum",
  "Colors": "Renkler",
  "Theme": "Tema",
  "Plugins": "Eklentiler",
  "Online": "Çevrimiçi",
  "Offline": "Çevrimdışı",
  "Mobile": "Mobil",
  "online": "çevrimiçi",
  "offline": "çevrimdışı",
  "mobile": "mobil",
  "Friends see you as {status}.": "Arkadaşların seni {status} görüyor.",
  "Parasite Offline isn't running: close League and open it again to appear offline.":
    "Parasite Offline çalışmıyor: çevrimdışı görünmek için League'i kapatıp yeniden aç.",
  "Couldn't reach Parasite Offline.": "Parasite Offline'a ulaşılamadı.",
  "Summoner names": "Sihirdar adları",
  "Lobby names": "Lobi adları",
  "Lobby header": "Lobi başlığı",
  "Queue (finding match)": "Sıra (maç aranıyor)",
  "League default": "League varsayılanı",
  "Default": "Varsayılan",
  "Reload client to apply": "Uygulamak için istemciyi yenile",
  "Add wallpaper": "Duvar kağıdı ekle",
  "Paste the file, type its name": "Dosyayı yapıştır, adını yaz",
  "Copy your picture or video into the folder that opened": "Resmini ya da videonu açılan klasöre kopyala",
  "{name} is your wallpaper": "{name} artık duvar kağıdın",
  "Not a video or image file name": "Video ya da resim dosyası adı değil",
  "{name} is not in the folder": "{name} klasörde yok",
  "16:9 Size Preferred": "16:9 boyut önerilir",
  "Use League's own background": "LoL'ün kendi arka planını kullan",
  "Add": "Ekle",
  "Delete": "Sil",
  "Drop files here, or Add to open the folder": "Dosyaları buraya bırak ya da klasörü açmak için Ekle'ye bas",
  "Keep at least one": "En az bir tane kalmalı",
  "{name} isn't a {type} file": "{name} bir {type} dosyası değil",
  "Adding {name}...": "{name} ekleniyor...",
  "Large package, this can take a while": "Paket boyutları büyük olduğu için işlem uzun sürebilir",
  "Parasite isn't connected": "Parasite bağlı değil",
  "Parasite didn't answer": "Parasite cevap vermedi",
  "What's new in Parasite {version}": "Parasite {version} yenilikleri",
  "Got it": "Tamam",
  "Backup": "Yedek",
  "Keep your settings in a file, or bring them from another PC.": "Ayarlarını bir dosyada sakla ya da başka bir bilgisayardan getir.",
  "Export settings": "Ayarları dışa aktar",
  "Import settings": "Ayarları içe aktar",
  "Saved as Parasite-settings.json": "Parasite-settings.json olarak kaydedildi",
  "Settings imported, reloading the client...": "Ayarlar içe aktarıldı, istemci yenileniyor...",
  "That isn't a Parasite settings file.": "Bu bir Parasite ayar dosyası değil.",
  "Appearance": "Görünüm",
  "Wallpaper": "Duvar kağıdı",
  "Lobby Reveal": "Lobby Reveal",
  "Parasite core": "Parasite çekirdeği",
  "Advanced": "Gelişmiş",
  "Close": "Kapat",
  "Injection, the League path, custom mods and troubleshooting live in Parasite's core settings.":
    "Enjeksiyon, League yolu, özel modlar ve sorun giderme Parasite'un çekirdek ayarlarında.",
  "Open core settings": "Çekirdek ayarlarını aç",
  "Custom skins": "Özel skinler",
  "Open the custom skins folder": "Özel skin klasörünü aç",
  "Press + and paste your custom skin files (.zip, .fantome, .modpkg) into the folder that opens, or drop them here. A skin that is on plays when you go into a game with that champion's default skin.":
    "+'ya bas ve açılan klasöre özel skin dosyalarını (.zip, .fantome, .modpkg) yapıştır ya da buraya sürükle. Açık olan skin, o şampiyonla default skinde oyuna girince oynar.",
  "No custom skins yet.": "Henüz özel skin yok.",
  "This file can't be read": "Bu dosya okunamıyor",
  "Pick the champion": "Şampiyonu seç",
  "Change the champion": "Şampiyonu değiştir",
  "Welcome": "Hoş geldin",
  "Unranked": "Derecesiz",
  "Iron": "Demir", "Bronze": "Bronz", "Silver": "Gümüş", "Gold": "Altın", "Platinum": "Platin", "Emerald": "Zümrüt",
  "Diamond": "Elmas", "Master": "Ustalık", "Grandmaster": "Üstatlık", "Challenger": "Şampiyonluk",
  "Ranked Solo/Duo": "Dereceli Tek/Çift", "Ranked Flex": "Dereceli Esnek", "Normal": "Normal", "Quickplay": "Hızlı Oyun",
  "Match": "Maç", "Last match": "Son maç", "Victory": "Galibiyet", "Defeat": "Mağlubiyet", "W": "G", "L": "M",
  "Level {level}": "Seviye {level}",
  "{region} cutoffs:": "{region} sınırları:",
  "{lp} LP to {rank}": "{rank} için {lp} LP",
  "Parasite is ready": "Parasite hazır",
  "Your status, look, skins and plugins, all in one place.": "Durumun, görünümün, skinlerin ve eklentilerin tek yerde.",
  "On": "Açık",
  "Off": "Kapalı"
};
function parasiteTr(text, vars) {
  const i18n = window.ParasiteI18n;
  let out = i18n && i18n.language === "tr" && PARASITE_TR[text] ? PARASITE_TR[text] : i18n ? i18n.t(text) : text;
  if (vars) out = out.replace(/\\{(\\w+)\\}/g, (match, key) => (key in vars ? String(vars[key]) : match));
  return out;
}

// Parasite: the desktop app picks the wallpaper. Its choice comes over the bridge when the
// theme starts and whenever it changes; the theme tells the app what it shows.
let parasiteWallpaperSent = "";
function parasiteWallpaperState(force = false) {
  const bridge = window.__parasiteBridge;
  if (!bridge) return;
  const list = ElainaData.get("Wallpaper-list") || [];
  const league = !!ElainaData.get("parasite-league-background");
  const name = list[ElainaData.get("wallpaper-index")] || "";
  const key = `${league}|${name}`;
  if (!force && key === parasiteWallpaperSent) return;
  parasiteWallpaperSent = key;
  bridge.send({ type: "parasite-wallpaper", action: "state", league, name });
}
async function parasiteApplyWallpaper(msg) {
  if (!msg || msg.action !== "apply") return;
  if (typeof msg.rev === "number" && msg.rev === ElainaData.get("parasite-wallpaper-rev")) {
    parasiteWallpaperState(true);
    return;
  }
  console.log("[PARASITE] wallpaper from the app:", msg.league ? "League's own" : msg.name);
  // Save the choice first: if the client's home page has not loaded yet, the theme's
  // own start-up shows it from these values
  const league = !!msg.league;
  ElainaData.set("parasite-league-background", league);
  document.documentElement.classList.toggle("parasite-league-bg", league);
  if (msg.name) {
    const list = ElainaData.get("Wallpaper-list") || [];
    if (!list.includes(msg.name))
      ElainaData.set("Wallpaper-list", [...list, msg.name]);
    ElainaData.set("wallpaper-index", ElainaData.get("Wallpaper-list").indexOf(msg.name));
  }
  if (typeof msg.rev === "number")
    ElainaData.set("parasite-wallpaper-rev", msg.rev);
  for (let i = 0; i < 240 && !document.getElementById("elaina-bg"); i++)
    await new Promise((resolve) => setTimeout(resolve, 500));
  const video = document.getElementById("elaina-bg");
  const image = document.getElementById("elaina-static-bg");
  const controls = document.querySelector(".wallpaper-controls");
  if (!video || !image) {
    parasiteWallpaperState(true);
    return;
  }
  if (league || ElainaData.get("disable-theme-wallpaper")) {
    video.pause();
    video.removeAttribute("src");
    video.load();
    image.removeAttribute("src");
    if (controls)
      controls.style.display = "none";
  } else {
    // A wallpaper picked in the app plays, even if the last one was paused
    if (ElainaData.get("pause-wallpaper") % 2 === 0)
      ElainaData.set("pause-wallpaper", ElainaData.get("pause-wallpaper") + 1);
    ElainaData.set("Wallpaper-currentTime", 0);
    setWallpaper();
    setImageWallpaper();
    video.classList.remove("webm-hidden");
    image.classList.remove("webm-hidden");
    video.play().catch((err) => console.warn("[PARASITE] wallpaper play", err));
    if (controls)
      controls.style.display = "flex";
    try {
      wallpaperController.playPauseSetIcon();
    } catch (err) {
      console.warn("[PARASITE] wallpaper icon", err);
    }
  }
  try {
    applyWindowEffect();
  } catch (err) {
    console.warn("[PARASITE] window effect", err);
  }
  parasiteWallpaperState(true);
}
function parasiteWallpaperLink(tries = 0) {
  const bridge = window.__parasiteBridge;
  if (!bridge) {
    if (tries < 120)
      setTimeout(() => parasiteWallpaperLink(tries + 1), 1000);
    return;
  }
  bridge.subscribe("parasite-wallpaper", (msg) => {
    parasiteApplyWallpaper(msg).catch((err) => console.warn("[PARASITE] wallpaper", err));
  });
  bridge.send({ type: "parasite-wallpaper", action: "get" });
  setTimeout(() => parasiteWallpaperState(true), 3000);
  // A wallpaper changed inside the client shows in the app too
  setInterval(() => parasiteWallpaperState(), 5000);
}

// Parasite: the profile page has its own background (the profile splash). While it is the
// page on screen the wallpaper fades out, so the two don't show through each other.
function parasiteProfileWallpaper() {
  let shown = null;
  const check = () => {
    const pages = document.querySelectorAll(
      '.screen-root[data-screen-name="rcp-fe-lol-profiles-main"], .rcp-fe-lol-profiles-main');
    let open = false;
    for (const page of pages) {
      open = page.checkVisibility
        ? page.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
        : page.getClientRects().length > 0;
      if (open) break;
    }
    if (open !== shown) {
      shown = open;
      document.documentElement.classList.toggle("parasite-profile-page", open);
    }
  };
  check();
  setInterval(check, 300);
}

function Settings(context) {
  ElainaData.set("settingsChangenumber", 0);
  mountParasiteHub();
  applyParasiteColors();
  parasiteWallpaperLink();
  parasiteProfileWallpaper();
}

// Parasite: the PARASITE item in the top navigation opens the Parasite hub, a centered window
// with tabs down the side. Rose's own settings stay in Rose's panel, opened from
// the last tab. Theme sections are the theme's own, sorted into the tabs.
async function parasiteThemeSections(page, sections) {
  for (const build of sections) {
    const built = await build();
    (Array.isArray(built) ? built : [built]).forEach((node) => node && page.appendChild(node));
  }
  // The theme starts its foldable rows folded; only this page's, not every page's
  page.querySelectorAll("#elaina-theme-settings-row-hide-button").forEach((button) => button.click());
}
const PARASITE_HUB_TABS = [
  { id: "status", label: "Status", icon: "status", render: async (page) => {
    parasiteHero(page);
    await newsCard(page);
    await statusSection(parasiteSection(page, parasiteTr("Status")));
  } },
  { id: "look", label: "Appearance", icon: "look", reload: true, render: async (page) => {
    colorSection(parasiteSection(page, parasiteTr("Colors")));
    await parasiteThemeSections(page, [infoSection, interfaceSection, profileSection, customAssetsSection, gameTabsSection]);
    if (typeof setWindowEffectsSettingsVisibility === "function") setWindowEffectsSettingsVisibility();
  } },
  { id: "wallpaper", label: "Wallpaper", icon: "wallpaper", reload: true, render: (page) =>
    parasiteThemeSections(page, [assetLibrarySection, wallpaperSection, audioSection]) },
  { id: "skins", label: "Custom skins", icon: "skins", render: (page) => customSkinsTab(page) },
  { id: "plugins", label: "Plugins", icon: "plugins", reload: true, render: async (page) => {
    await parasiteThemeSections(page, [coreSection, pluginsProfileSection]);
    const more = document.createElement("details");
    more.className = "parasite-hub-advanced";
    const summary = document.createElement("summary");
    summary.textContent = parasiteTr("Advanced");
    more.appendChild(summary);
    page.appendChild(more);
    await parasiteThemeSections(more, [updatesSection, developerSection]);
  } },
  // Drawn by the PARASITE-LobbyReveal plugin
  { id: "reveal", label: "Lobby Reveal", icon: "reveal", render: async (page) =>
    window.ParasiteReveal && window.ParasiteReveal.renderHub(page) },
  { id: "backup", label: "Backup", icon: "backup", render: (page) => backupSection(parasiteSection(page, parasiteTr("Backup"))) },
  { id: "core", label: "Parasite core", icon: "core", render: (page) => coreTab(parasiteSection(page, parasiteTr("Parasite core"))) },
];
// Small line icons for the side tabs, drawn in the tab's text color
const PARASITE_HUB_ICONS = {
  status: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  look: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.6 0-1.4-1.2-1.6-1.2-2.9 0-1 .8-1.5 1.8-1.5H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="14.5" cy="7" r="1"/>',
  wallpaper: '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M3 16l5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/>',
  plugins: '<path d="M9 3h6v4a2 2 0 1 1 0 4v2h4v6h-6v-2a2 2 0 1 0-4 0v2H3v-6h2a2 2 0 1 0 0-4H3V7h6z"/>',
  reveal: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 14.2c3 .3 5.5 2.6 5.5 5.8"/>',
  skins: '<path d="M12 3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.3 6.8 19l1-5.8-4.2-4.1 5.8-.8z"/>',
  backup: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
  core: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
};
function parasiteHubIcon(name) {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PARASITE_HUB_ICONS[name] || ""}</svg>`;
}
// Parasite: custom skins. + opens Parasite's "custom skins" folder (files are copied and pasted in),
// files dropped on the tab are sent to Parasite, and each skin is switched on or off. A
// switched-on skin plays when its champion goes into a game with the default skin.
const parasiteSkinWaiters = new Map();
let parasiteSkinRequests = 0;
let parasiteSkinsSubscribed = false;
function parasiteCustomSkins(action, extra = {}) {
  const bridge = window.__parasiteBridge;
  if (!bridge) return Promise.resolve({ error: parasiteTr("Parasite isn't connected"), skins: null });
  if (!parasiteSkinsSubscribed) {
    parasiteSkinsSubscribed = true;
    bridge.subscribe("parasite-custom-skins", (reply) => {
      const waiter = parasiteSkinWaiters.get(reply && reply.requestId);
      if (waiter) {
        parasiteSkinWaiters.delete(reply.requestId);
        waiter(reply);
      }
    });
  }
  const requestId = `${Date.now()}-${++parasiteSkinRequests}`;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      parasiteSkinWaiters.delete(requestId);
      resolve({ error: parasiteTr("Parasite didn't answer"), skins: null });
    }, 20000);
    parasiteSkinWaiters.set(requestId, (reply) => {
      clearTimeout(timer);
      resolve(reply);
    });
    bridge.send({ type: "parasite-custom-skins", action, requestId, ...extra });
  });
}
let parasiteChampionList = null;
async function parasiteChampions() {
  if (parasiteChampionList && parasiteChampionList.length) return parasiteChampionList;
  try {
    const all = await (await fetch("/lol-game-data/assets/v1/champion-summary.json")).json();
    parasiteChampionList = all.filter((champion) => champion.id > 0).sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    parasiteChampionList = [];
  }
  return parasiteChampionList;
}
async function customSkinsTab(page) {
  const section = parasiteSection(page, parasiteTr("Custom skins"));
  const head = document.createElement("div");
  head.className = "parasite-skins-head";
  const add = document.createElement("div");
  add.className = "parasite-skins-add";
  add.textContent = "+";
  add.title = parasiteTr("Open the custom skins folder");
  add.addEventListener("click", () => parasiteCustomSkins("open"));
  const help = document.createElement("div");
  help.className = "parasite-skins-help";
  help.textContent = parasiteTr("Press + and paste your custom skin files (.zip, .fantome, .modpkg) into the folder that opens, or drop them here. A skin that is on plays when you go into a game with that champion's default skin.");
  head.append(add, help);
  const hint = document.createElement("div");
  hint.className = "parasite-asset-hint";
  const list = document.createElement("div");
  list.className = "parasite-skins-list";
  section.append(head, hint, list);
  const champions = await parasiteChampions();
  const byId = new Map(champions.map((champion) => [champion.id, champion]));
  const byAlias = new Map(champions.map((champion) => [String(champion.alias).toLowerCase(), champion]));
  let shownKey = "";
  const say = (text, error) => {
    hint.textContent = text || "";
    hint.classList.toggle("error", Boolean(error && text));
  };
  const show = (skins) => {
    if (!Array.isArray(skins)) return;
    const key = JSON.stringify(skins);
    if (key === shownKey) return;
    shownKey = key;
    if (!skins.length) {
      const empty = document.createElement("div");
      empty.className = "parasite-skins-empty";
      empty.textContent = parasiteTr("No custom skins yet.");
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren(...skins.map((skin) => {
      const champion = byId.get(skin.championId);
      const row = document.createElement("div");
      row.className = "parasite-skin-row" + (skin.enabled ? " on" : "");
      const icon = document.createElement("div");
      icon.className = "parasite-skin-icon";
      if (champion) {
        icon.style.backgroundImage = `url(/lol-game-data/assets/v1/champion-icons/${champion.id}.png)`;
        icon.classList.add("changeable");
        icon.title = parasiteTr("Change the champion");
        icon.addEventListener("click", async () => {
          const reply = await parasiteCustomSkins("set", { name: skin.name, championId: 0 });
          say(reply.error, true);
          show(reply.skins);
        });
      }
      const text = document.createElement("div");
      text.className = "parasite-skin-text";
      const title = document.createElement("div");
      title.className = "parasite-skin-title";
      title.textContent = skin.title;
      const sub = document.createElement("div");
      sub.className = "parasite-skin-sub";
      sub.textContent = skin.broken ? parasiteTr("This file can't be read") : `${champion ? champion.name + " · " : ""}${skin.name}`;
      text.append(title, sub);
      row.append(icon, text);
      if (!champion && !skin.broken) {
        const pick = document.createElement("select");
        pick.className = "parasite-skin-pick";
        const none = document.createElement("option");
        none.value = "";
        none.textContent = parasiteTr("Pick the champion");
        pick.appendChild(none);
        champions.forEach((option) => {
          const item = document.createElement("option");
          item.value = String(option.id);
          item.textContent = option.name;
          pick.appendChild(item);
        });
        pick.addEventListener("change", async () => {
          if (!pick.value) return;
          const reply = await parasiteCustomSkins("set", { name: skin.name, championId: Number(pick.value) });
          say(reply.error, true);
          show(reply.skins);
        });
        row.appendChild(pick);
      }
      const toggle = document.createElement("div");
      toggle.className = "parasite-skin-toggle" + (skin.enabled ? " on" : "") + (champion ? "" : " off-limits");
      toggle.title = champion ? parasiteTr(skin.enabled ? "On" : "Off") : parasiteTr("Pick the champion");
      toggle.addEventListener("click", async () => {
        if (!champion) return;
        const reply = await parasiteCustomSkins("set", { name: skin.name, enabled: !skin.enabled });
        say(reply.error, true);
        show(reply.skins);
      });
      row.appendChild(toggle);
      return row;
    }));
  };
  let busy = false;
  const refresh = async () => {
    if (busy) return;
    const reply = await parasiteCustomSkins("list");
    if (reply.error) {
      say(reply.error, true);
      return;
    }
    // A skin whose WAD names its champion gets that champion by itself
    for (const skin of reply.skins || []) {
      if (skin.championId || skin.broken || skin.auto === false) continue;
      const match = (skin.wads || []).map((wad) => byAlias.get(wad)).find(Boolean);
      if (match) {
        const set = await parasiteCustomSkins("set", { name: skin.name, championId: match.id });
        if (Array.isArray(set.skins)) reply.skins = set.skins;
      }
    }
    show(reply.skins);
  };
  // Files copied into the folder show up while the tab is open
  const timer = setInterval(() => {
    if (!document.body.contains(page)) { clearInterval(timer); return; }
    if (page.classList.contains("active")) refresh();
  }, 2500);
  section.addEventListener("dragover", (event) => {
    event.preventDefault();
    section.parentElement.classList.add("dragging");
  });
  section.addEventListener("dragleave", () => section.parentElement.classList.remove("dragging"));
  section.addEventListener("drop", async (event) => {
    event.preventDefault();
    section.parentElement.classList.remove("dragging");
    busy = true;
    for (const file of [...((event.dataTransfer && event.dataTransfer.files) || [])]) {
      say(parasiteAddingText(file));
      const total = Math.max(1, Math.ceil(file.size / PARASITE_ASSET_CHUNK));
      let error = "";
      for (let index = 0; index < total && !error; index++) {
        const data = await parasiteBlobToBase64(file.slice(index * PARASITE_ASSET_CHUNK, (index + 1) * PARASITE_ASSET_CHUNK));
        error = (await parasiteCustomSkins("chunk", { name: file.name, index, total, data })).error;
        if (!error && index + 1 < total) say(parasiteAddingText(file, (index + 1) / total));
      }
      say(error, true);
    }
    busy = false;
    refresh();
  });
  await refresh();
}
// The welcome card on top of the Status tab: the player, their rank and their
// last match, on that champion's splash art. Read from the client, kept for next time.
const PARASITE_TIERS = { IRON: "Iron", BRONZE: "Bronze", SILVER: "Silver", GOLD: "Gold", PLATINUM: "Platinum",
  EMERALD: "Emerald", DIAMOND: "Diamond", MASTER: "Master", GRANDMASTER: "Grandmaster", CHALLENGER: "Challenger" };
const PARASITE_QUEUES = { 420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal", 430: "Normal", 490: "Quickplay",
  480: "Quickplay", 450: "ARAM", 1700: "Arena", 1900: "URF", 900: "URF" };
// The server's Challenger and Grandmaster cutoffs, read by Parasite from replays.lol
let parasiteCutoffWaiter = null;
function parasiteCutoffs(region) {
  const bridge = window.__parasiteBridge;
  if (!bridge || !region) return Promise.resolve(null);
  if (!parasiteCutoffs.subscribed) {
    parasiteCutoffs.subscribed = true;
    bridge.subscribe("parasite-cutoffs", (reply) => parasiteCutoffWaiter && parasiteCutoffWaiter(reply));
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 15000);
    parasiteCutoffWaiter = (reply) => { clearTimeout(timer); resolve(reply && reply.cutoff); };
    bridge.send({ type: "parasite-cutoffs", region, requestId: String(Date.now()) });
  });
}
async function parasiteHeroData() {
  const get = async (path) => {
    const response = await fetch(path);
    if (!response.ok) throw new Error(path);
    return response.json();
  };
  const summoner = await get("/lol-summoner/v1/current-summoner");
  const data = { name: summoner.gameName || summoner.displayName || "", tag: summoner.tagLine || "",
    level: summoner.summonerLevel || 0 };
  try {
    const solo = ((await get("/lol-ranked/v1/current-ranked-stats")).queueMap || {}).RANKED_SOLO_5x5 || {};
    const tier = solo.tier && solo.tier !== "NONE" ? solo.tier : "";
    let rank = tier ? parasiteTr(PARASITE_TIERS[tier] || tier) : parasiteTr("Unranked");
    if (tier && solo.division && solo.division !== "NA" && !["MASTER", "GRANDMASTER", "CHALLENGER"].includes(tier)) rank += ` ${solo.division}`;
    if (tier) rank += ` · ${solo.leaguePoints || 0} LP`;
    Object.assign(data, { rank, wins: solo.wins || 0, losses: solo.losses || 0, lp: solo.leaguePoints || 0,
      tier: tier.toLowerCase() });
  } catch (error) {}
  try {
    data.cutoff = await parasiteCutoffs((await get("/riotclient/region-locale")).region);
  } catch (error) {}
  try {
    const games = ((await get("/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=1")).games || {}).games || [];
    if (games.length) {
      const player = games[0].participants[0];
      const stats = player.stats || {};
      const champion = await get(`/lol-game-data/assets/v1/champions/${player.championId}.json`);
      const skin = (champion.skins || [])[0] || {};
      data.last = { champion: champion.name || "", win: !!stats.win, kda: `${stats.kills || 0}/${stats.deaths || 0}/${stats.assists || 0}`,
        queue: parasiteTr(PARASITE_QUEUES[games[0].queueId] || "Match"), splash: skin.uncenteredSplashPath || skin.splashPath || "" };
    }
  } catch (error) {}
  return data;
}
function parasiteHeroFill(hero, data) {
  const make = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls, textContent: text });
  const body = make("div", "parasite-hero-body", "");
  body.appendChild(make("small", "", parasiteTr("Parasite is ready") + " · " + parasiteTr("Welcome")));
  const title = make("b", "", data && data.name ? data.name : parasiteTr("Parasite is ready"));
  if (data && data.tag) title.appendChild(make("i", "", ` #${data.tag}`));
  body.appendChild(title);
  const chips = make("div", "parasite-hero-chips", "");
  if (data && data.rank) chips.appendChild(make("span", "parasite-chip rank", data.rank));
  if (data && (data.wins || data.losses)) {
    const total = data.wins + data.losses;
    chips.appendChild(make("span", "parasite-chip", `${data.wins}${parasiteTr("W")} ${data.losses}${parasiteTr("L")} · %${Math.round(data.wins * 100 / total)}`));
  }
  if (data && data.level) chips.appendChild(make("span", "parasite-chip", parasiteTr("Level {level}", { level: data.level })));
  if (chips.childElementCount) body.appendChild(chips);
  else body.appendChild(make("span", "", parasiteTr("Your status, look, skins and plugins, all in one place.")));
  const cut = data && data.cutoff;
  if (cut) {
    const row = make("div", "parasite-hero-cut", "");
    row.append(make("span", "", parasiteTr("{region} cutoffs:", { region: cut.region })),
      make("span", "parasite-cut gm", `${parasiteTr("Grandmaster")} ${cut.grandmaster} LP`),
      make("span", "parasite-cut ch", `${parasiteTr("Challenger")} ${cut.challenger} LP`));
    const apex = data.tier === "grandmaster" || data.tier === "challenger";
    const target = apex ? cut.challenger : data.tier === "master" ? cut.grandmaster : 0;
    if (target && data.lp < target) {
      row.appendChild(make("span", "parasite-cut-need",
        parasiteTr("{lp} LP to {rank}", { lp: target - data.lp, rank: parasiteTr(apex ? "Challenger" : "Grandmaster") })));
    }
    body.appendChild(row);
  }
  const parts = [body];
  if (data && data.last) {
    const last = make("div", "parasite-hero-last", "");
    last.append(make("small", "", parasiteTr("Last match")), make("b", "", data.last.champion),
      make("span", "parasite-hero-result " + (data.last.win ? "win" : "loss"), parasiteTr(data.last.win ? "Victory" : "Defeat")),
      make("span", "", `${data.last.kda} · ${data.last.queue}`));
    parts.push(last);
  }
  const art = make("div", "parasite-hero-art", "");
  if (data && data.last && data.last.splash) {
    const img = new Image();
    img.onload = () => { art.style.backgroundImage = `url("${img.src}")`; art.classList.add("on"); };
    img.src = data.last.splash;
  }
  hero.replaceChildren(art, ...parts);
}
function parasiteHero(page) {
  const hero = document.createElement("div");
  hero.className = "parasite-hero";
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("parasite-hero") || "null"); } catch (error) {}
  parasiteHeroFill(hero, saved);
  page.appendChild(hero);
  parasiteHeroData().then((data) => {
    try { localStorage.setItem("parasite-hero", JSON.stringify(data)); } catch (error) {}
    if (document.body.contains(hero) && JSON.stringify(data) !== JSON.stringify(saved)) parasiteHeroFill(hero, data);
  }).catch(() => {});
}
// Rose's own settings (injection, game path, mods) keep their panel.
function coreTab(section) {
  const note = document.createElement("div");
  note.className = "parasite-customize-state";
  note.textContent = parasiteTr("Injection, the League path, custom mods and troubleshooting live in Parasite's core settings.");
  const open = document.createElement("lol-uikit-flat-button");
  open.className = "parasite-hub-primary";
  open.textContent = parasiteTr("Open core settings");
  open.addEventListener("click", () => {
    closeParasiteHub();
    const navItem = document.querySelector("lol-uikit-navigation-item.menu_item_Golden");
    window.dispatchEvent(new CustomEvent("parasite-open-settings", { detail: { navItem, parasiteCore: true } }));
  });
  section.append(note, open);
}

// Parasite Offline (parasite/offline) takes commands as chat messages to its "Parasite Active!" friend.
const PARASITE_OFFLINE_ID = "41c322a1-b328-495b-a004-5ccd3e45eae8@eu1.pvp.net";
const PARASITE_OFFLINE_STATUSES = [
  { command: "online", label: "Online", color: "#0acf83" },
  { command: "offline", label: "Offline", color: "#9a9a9a" },
  { command: "mobile", label: "Mobile", color: "#e8a33a" }
];
async function parasiteOfflineRunning() {
  try {
    const friends = await (await fetch("/lol-chat/v1/friends")).json();
    return friends.some((friend) => String(friend.pid || friend.id || "").startsWith(PARASITE_OFFLINE_ID.split("@")[0]));
  } catch {
    return false;
  }
}
async function parasiteOfflineStatus() {
  try {
    const messages = await (await fetch(`/lol-chat/v1/conversations/${encodeURIComponent(PARASITE_OFFLINE_ID)}/messages`)).json();
    for (const message of [...messages].reverse()) {
      const match = /appearing (online|offline|mobile)/i.exec(message.body || "");
      if (match)
        return match[1].toLowerCase();
    }
  } catch {}
  return "";
}
async function sendParasiteOffline(command) {
  const url = `/lol-chat/v1/conversations/${encodeURIComponent(PARASITE_OFFLINE_ID)}/messages`;
  const post = () => fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body: command, type: "chat" })
  });
  let response = await post();
  if (!response.ok) {
    await fetch("/lol-chat/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: PARASITE_OFFLINE_ID, type: "chat" })
    }).catch(() => {});
    response = await post();
  }
  return response.ok;
}
function parasiteSection(view, title) {
  const section = document.createElement("div");
  section.className = "parasite-hub-section";
  const heading = document.createElement("div");
  heading.className = "parasite-hub-title";
  heading.textContent = title;
  // The theme's settings prepend into the box they get, so that box is below the title.
  const body = document.createElement("div");
  section.append(heading, body);
  view.appendChild(section);
  return body;
}
async function statusSection(section) {
  const row = document.createElement("div");
  row.className = "parasite-status-row";
  const note = document.createElement("div");
  note.className = "parasite-customize-state";
  section.append(row, note);
  if (!await parasiteOfflineRunning()) {
    note.textContent = parasiteTr("Parasite Offline isn't running: close League and open it again to appear offline.");
    return;
  }
  let current = await parasiteOfflineStatus() || localStorage.getItem("parasite-offline-status") || "offline";
  const buttons = PARASITE_OFFLINE_STATUSES.map(({ command, label, color }) => {
    const button = document.createElement("lol-uikit-flat-button");
    button.style.setProperty("--parasite-status", color);
    const dot = document.createElement("span");
    dot.className = "parasite-status-dot";
    button.append(dot, document.createTextNode(parasiteTr(label)));
    button.addEventListener("click", async () => {
      if (!await sendParasiteOffline(command)) {
        note.textContent = parasiteTr("Couldn't reach Parasite Offline.");
        return;
      }
      current = command;
      try {
        localStorage.setItem("parasite-offline-status", command);
      } catch {}
      show();
    });
    row.appendChild(button);
    return { command, button };
  });
  const show = () => {
    buttons.forEach(({ command, button }) => button.classList.toggle("parasite-status-active", command === current));
    note.textContent = parasiteTr("Friends see you as {status}.", { status: parasiteTr(current) });
  };
  show();
}

// Text colors players pick in the CUSTOMIZE tab. Empty means League's own color.
const PARASITE_COLORS = [
  { key: "parasite-color-names", label: "Summoner names",
    selector: "span.player-name__force-locale-text-direction" },
  { key: "parasite-color-lobby-names", label: "Lobby names",
    selector: ".parties-player-name, .v2-banner-component .player-name, .player-slot__summoner-name" },
  { key: "parasite-color-lobby-header", label: "Lobby header",
    selector: ".lobby-header-description, .lobby-header-separator, .lobby-header-details" },
  { key: "parasite-color-queue", label: "Queue (finding match)",
    selector: ".parties-game-search-header-text, .parties-status-card-header-text, .parties-game-search-elapsed, .parties-game-search-status, .parties-status-card-info" }
];
function applyParasiteColors() {
  let style = document.getElementById("parasite-custom-colors");
  if (!style) {
    style = document.createElement("style");
    style.id = "parasite-custom-colors";
    document.head.appendChild(style);
  }
  style.textContent = PARASITE_COLORS
    .filter((item) => ElainaData.get(item.key))
    .map((item) => `${item.selector} { color: ${utils.sanitizeColor(ElainaData.get(item.key))} !important; }`)
    .join("\\n");
}
// What changed in this version (PARASITE-News/whats-new.json), shown once per version.
async function newsCard(view) {
  let news;
  try {
    news = await (await fetch("//plugins/PARASITE-News/whats-new.json")).json();
  } catch {
    return;
  }
  let seen = "";
  try {
    seen = localStorage.getItem("parasite-news-seen") || "";
  } catch {}
  if (!news || !news.version || seen === news.version)
    return;
  const language = window.ParasiteI18n && window.ParasiteI18n.language === "tr" ? "tr" : "en";
  const items = news[language] || news.en || [];
  const card = document.createElement("div");
  card.className = "parasite-news";
  const title = document.createElement("div");
  title.className = "parasite-news-title";
  title.textContent = parasiteTr("What's new in Parasite {version}", { version: news.version });
  const list = document.createElement("ul");
  items.forEach((item) => {
    const entry = document.createElement("li");
    entry.textContent = item;
    list.appendChild(entry);
  });
  const done = document.createElement("lol-uikit-flat-button");
  done.textContent = parasiteTr("Got it");
  done.addEventListener("click", () => {
    try {
      localStorage.setItem("parasite-news-seen", news.version);
    } catch {}
    card.remove();
  });
  card.append(title, list, done);
  view.appendChild(card);
}
// Every theme setting plus the parasite-* ones other plugins keep in localStorage
// (Lobby Reveal's choices and box position), in one file to take to another PC.
function exportParasiteSettings() {
  const local = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith("parasite-"))
        local[key] = localStorage.getItem(key);
    }
  } catch {}
  const backup = { app: "Parasite", format: 1, saved: new Date().toISOString(), theme: ElainaData.getAll(), local };
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" }));
  link.download = "Parasite-settings.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}
function backupSection(section) {
  const row = document.createElement("div");
  row.className = "parasite-status-row";
  const note = document.createElement("div");
  note.className = "parasite-customize-state";
  note.textContent = parasiteTr("Keep your settings in a file, or bring them from another PC.");
  const save = document.createElement("lol-uikit-flat-button");
  save.textContent = parasiteTr("Export settings");
  save.addEventListener("click", () => {
    exportParasiteSettings();
    note.textContent = parasiteTr("Saved as Parasite-settings.json");
  });
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json,application/json";
  input.style.display = "none";
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    try {
      const backup = JSON.parse(await file.text());
      if (!backup || backup.app !== "Parasite" || typeof backup.theme !== "object")
        throw new Error("not a Parasite settings file");
      ElainaData.setAll(backup.theme);
      if (ElainaData.flush) await ElainaData.flush();
      for (const [key, value] of Object.entries(backup.local || {})) {
        if (key.startsWith("parasite-") && typeof value === "string") {
          try {
            localStorage.setItem(key, value);
          } catch {}
        }
      }
      note.textContent = parasiteTr("Settings imported, reloading the client...");
      setTimeout(() => window.restartClient(), 1500);
    } catch {
      note.textContent = parasiteTr("That isn't a Parasite settings file.");
    }
  });
  const load = document.createElement("lol-uikit-flat-button");
  load.textContent = parasiteTr("Import settings");
  load.addEventListener("click", () => input.click());
  row.append(save, load, input);
  section.append(row, note);
}
function colorSection(section) {
  const list = document.createElement("div");
  list.className = "parasite-customize";
  PARASITE_COLORS.forEach((item) => {
    const row = document.createElement("div");
    row.className = "parasite-customize-row";
    const label = document.createElement("span");
    label.textContent = parasiteTr(item.label);
    const picker = document.createElement("input");
    picker.type = "color";
    picker.value = ElainaData.get(item.key) || "#f0e6d2";
    const state = document.createElement("span");
    state.className = "parasite-customize-state";
    const showState = () => {
      state.textContent = ElainaData.get(item.key) ? ElainaData.get(item.key) : parasiteTr("League default");
    };
    picker.addEventListener("input", () => {
      ElainaData.set(item.key, picker.value);
      showState();
      applyParasiteColors();
    });
    const reset = document.createElement("lol-uikit-flat-button");
    reset.textContent = parasiteTr("Default");
    reset.addEventListener("click", () => {
      ElainaData.set(item.key, "");
      picker.value = "#f0e6d2";
      showState();
      applyParasiteColors();
    });
    showState();
    row.append(label, picker, state, reset);
    list.appendChild(row);
  });
  section.appendChild(list);
}
const PARASITE_PANEL_CSS = `
  #parasite-hub-backdrop { position: fixed; inset: 0; z-index: 10050; display: flex; align-items: center;
    justify-content: center; background: rgba(1, 4, 9, .62); }
  #parasite-hub { display: flex; width: min(860px, 92vw); height: min(600px, 86vh); background: #010a13;
    border: 1px solid #785a28; border-top: 2px solid #a78bfa; box-shadow: 0 12px 40px rgba(0, 0, 0, .6);
    color: #cdbe91; font-family: "Spiegel", "Arial", sans-serif; }
  .parasite-hub-side { flex: 0 0 190px; display: flex; flex-direction: column; padding: 16px 0;
    background: #0a0f1a; border-right: 1px solid #785a2866; }
  .parasite-hub-logo { padding: 0 18px 14px; color: #a78bfa; font: 700 18px "Beaufort for LOL", serif; letter-spacing: 3px; }
  .parasite-hub-tab { display: flex; align-items: center; gap: 10px; padding: 10px 18px; cursor: pointer; color: #a09b8c;
    font-size: 13px; border-left: 2px solid transparent; }
  .parasite-hub-tab svg { color: #6f6a60; flex: 0 0 auto; }
  .parasite-hub-tab:hover { color: #f0e6d2; background: #ffffff08; }
  .parasite-hub-tab.active { color: #f0e6d2; background: #8b5cf61f; border-left-color: #a78bfa; }
  .parasite-hub-tab.active svg { color: #a78bfa; }
  .parasite-hub-version { margin-top: auto; padding: 0 18px; color: #5b5a56; font-size: 11px; }
  .parasite-hub-main { position: relative; flex: 1; min-width: 0; overflow-y: auto; padding: 20px 26px 24px; }
  .parasite-hub-main::-webkit-scrollbar { width: 6px; }
  .parasite-hub-main::-webkit-scrollbar-thumb { background: #785a28; }
  .parasite-hub-close { position: absolute; top: 12px; right: 14px; cursor: pointer; color: #7e7a70; font-size: 18px; line-height: 1; }
  .parasite-hub-close:hover { color: #f0e6d2; }
  .parasite-hub-page { display: none; }
  .parasite-hub-page.active { display: block; }
  .parasite-hub-primary { display: inline-block; margin-top: 12px; min-width: 200px; }
  .parasite-panel-reload { display: block; width: 220px; margin: 18px 0 4px; }
  .parasite-hub-advanced { margin-top: 14px; border-top: 1px solid #785a2840; padding-top: 10px; }
  .parasite-hub-advanced > summary { cursor: pointer; color: #7e7a70; font-size: 12px; letter-spacing: .5px; }
  .parasite-hub-advanced > summary:hover { color: #cdbe91; }
  /* The theme's own sections, drawn in the hub's style */
  #parasite-hub .theme-settings-section { margin: 0 0 18px; padding: 0; border: 0; background: none; }
  #parasite-hub .theme-settings-section-title { display: block; margin: 0 0 10px; padding: 0 0 6px;
    border-bottom: 1px solid #785a2866; color: #f0e6d2; font: 700 13px "Beaufort for LOL", serif;
    letter-spacing: 1px; text-transform: uppercase; }
  #parasite-hub .theme-settings-section-content { display: flex; flex-direction: column; gap: 6px; }
  #parasite-hub lol-uikit-flat-checkbox { margin: 2px 0; }
  #parasite-hub .parasite-theme-settings-row { color: #cdbe91; font-size: 13px; }
  #parasite-hub p, #parasite-hub label { color: #cdbe91; }
  #parasite-hub .parasite-reveal-hub, #parasite-hub .parasite-rv-hub { margin: 0; }
  .parasite-hub-section { margin-bottom: 18px; }
  .parasite-hub-title { margin: 0 0 8px; padding-bottom: 4px; border-bottom: 1px solid #785a2866; color: #f0e6d2;
    font: 700 13px "Beaufort for LOL", serif; letter-spacing: 1px; text-transform: uppercase; }
  .parasite-status-row { display: flex; gap: 8px; margin-bottom: 6px; }
  .parasite-status-row lol-uikit-flat-button { flex: 1; }
  .parasite-status-row .parasite-status-active { filter: brightness(1.25); outline: 1px solid var(--parasite-status, #c8aa6e); }
  .parasite-status-dot { display: inline-block; width: 8px; height: 8px; margin-right: 8px; border-radius: 50%;
    vertical-align: 1px; background: var(--parasite-status, #9a9a9a); }
  .parasite-news { margin: 0 0 18px; padding: 12px 14px; border: 1px solid #c8aa6e;
    background: linear-gradient(160deg, #1b1430 0%, #010a13 80%); color: #cdbe91; font-size: 12px; }
  .parasite-news-title { margin-bottom: 6px; color: #f0e6d2; font: 700 14px "Beaufort for LOL", serif; letter-spacing: 1px; }
  .parasite-news ul { margin: 0 0 10px; padding-left: 18px; line-height: 1.6; }
  .parasite-news lol-uikit-flat-button { width: 120px; }
  .parasite-asset-row { margin: 10px 0; padding: 10px; border: 1px dashed #785a2866; transition: border-color .15s, background .15s; }
  .parasite-asset-row.dragging { border-color: #c8aa6e; background: #c8aa6e14; }
  .parasite-asset-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;
    color: #f0e6d2; font: 700 13px "Beaufort for LOL", serif; }
  .parasite-asset-head lol-uikit-flat-button { width: 110px; }
  .parasite-asset-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .parasite-asset-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 4px 3px 8px;
    border: 1px solid #3c3c41; background: #1e2328; color: #cdbe91; font-size: 12px; }
  .parasite-asset-remove { cursor: pointer; padding: 0 4px; color: #a09b8c; font-size: 14px; line-height: 1; }
  .parasite-asset-remove:hover { color: #e84057; }
  .parasite-asset-hint { margin-top: 8px; color: #7e7a70; font-size: 11px; }
  .parasite-asset-hint.error { color: #e84057; }
  .parasite-hub-section.dragging { outline: 1px dashed #a78bfa; outline-offset: 6px; }
  .parasite-skins-head { display: flex; align-items: center; gap: 14px; margin: 4px 0 10px; }
  .parasite-skins-add { flex: 0 0 auto; display: flex; align-items: center; justify-content: center; width: 40px; height: 40px;
    border: 1px solid #a78bfa; border-radius: 50%; color: #a78bfa; font: 300 28px/1 "Spiegel", "Arial", sans-serif;
    cursor: pointer; transition: background .15s, color .15s; }
  .parasite-skins-add:hover { background: #a78bfa; color: #010a13; }
  .parasite-skins-help { color: #a09b8c; font-size: 12px; line-height: 1.5; }
  .parasite-skins-list { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
  .parasite-skins-empty { padding: 18px; border: 1px dashed #785a2866; color: #7e7a70; font-size: 12px; text-align: center; }
  .parasite-skin-row { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border: 1px solid #1e2328; background: #0a0f1a; }
  .parasite-skin-row.on { border-color: #a78bfa80; background: #8b5cf614; }
  .parasite-skin-icon { flex: 0 0 36px; height: 36px; border: 1px solid #785a28; background: #1e2328 center / cover no-repeat; }
  .parasite-skin-icon.changeable { cursor: pointer; }
  .parasite-skin-icon.changeable:hover { border-color: #a78bfa; }
  .parasite-skin-text { flex: 1; min-width: 0; }
  .parasite-skin-title { color: #f0e6d2; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .parasite-skin-sub { color: #7e7a70; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .parasite-skin-pick { background: #1e2328; color: #cdbe91; border: 1px solid #785a28; padding: 4px; font-size: 12px; max-width: 150px; }
  .parasite-skin-toggle { position: relative; flex: 0 0 38px; height: 20px; border-radius: 10px; background: #3c3c41; cursor: pointer;
    transition: background .15s; }
  .parasite-skin-toggle::after { content: ""; position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%;
    background: #a09b8c; transition: left .15s, background .15s; }
  .parasite-skin-toggle.on { background: #a78bfa; }
  .parasite-skin-toggle.on::after { left: 21px; background: #f0e6d2; }
  .parasite-skin-toggle.off-limits { opacity: .4; cursor: default; }
  /* Parasite hub, app style: an icon rail whose tiles grow under the mouse, rounded cards */
  #parasite-hub { width: min(920px, 94vw); background: #16141f; border: 1px solid #2e2a3d; border-radius: 20px;
    overflow: hidden; box-shadow: 0 24px 60px rgba(0, 0, 0, .6); }
  .parasite-hub-side { flex: 0 0 76px; align-items: center; gap: 12px; padding: 18px 0; background: #100e17; border-right: 1px solid #1c1926; }
  .parasite-hub-logo { width: 44px; height: 44px; padding: 0; margin-bottom: 6px; border-radius: 14px; display: grid; place-items: center;
    background: linear-gradient(135deg, #7c3aed, #db2777); color: #fff; font: 800 20px Georgia, serif; letter-spacing: 0;
    box-shadow: 0 6px 18px rgba(124, 58, 237, .35); }
  .parasite-hub-tab { position: relative; width: 44px; height: 44px; padding: 0; justify-content: center; border-left: 0; border-radius: 13px;
    background: #1d1a29; color: #a3a0ad; transition: transform .18s cubic-bezier(.3, 1.6, .5, 1), background .15s, color .15s; }
  .parasite-hub-tab svg { width: 20px; height: 20px; color: inherit; }
  .parasite-hub-tab:hover { transform: scale(1.18); background: #2a2540; color: #f0eef5; }
  .parasite-hub-tab.active { background: linear-gradient(135deg, #7c3aed, #a78bfa); color: #fff; border-left-color: transparent;
    box-shadow: 0 6px 16px rgba(124, 58, 237, .4); }
  .parasite-hub-tab.active svg { color: #fff; }
  .parasite-hub-tab::after { content: attr(data-label); position: absolute; left: 56px; top: 50%; padding: 5px 10px; border-radius: 8px;
    background: #2a2540; color: #f0eef5; font-size: 12px; white-space: nowrap; opacity: 0; pointer-events: none; z-index: 5;
    transform: translate(-6px, -50%); transition: .15s; }
  .parasite-hub-tab:hover::after { opacity: 1; transform: translate(0, -50%); }
  .parasite-hub-main { background: #16141f; padding: 16px 26px 24px; }
  .parasite-hub-main::-webkit-scrollbar-thumb { background: #2e2a3d; border-radius: 8px; }
  .parasite-hub-heading { display: flex; align-items: center; gap: 10px; margin: 0 0 14px; color: #f0eef5; font: 600 17px "Spiegel", "Arial", sans-serif; }
  .parasite-hub-version { margin: 0; padding: 3px 10px; border-radius: 99px; background: #211e2d; border: 1px solid #2e2a3d; color: #a3a0ad; font-size: 11px; font-weight: 400; }
  .parasite-hub-close { top: 16px; right: 18px; width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; }
  .parasite-hub-close:hover { background: #c42b4a; color: #fff; }
  .parasite-hero { position: relative; overflow: hidden; margin-bottom: 14px; padding: 18px 20px; min-height: 120px; border-radius: 18px;
    color: #fff; display: flex; align-items: flex-end; gap: 14px;
    background: linear-gradient(120deg, #7c3aed 0%, #a21caf 55%, #db2777 100%); }
  .parasite-hero-art { position: absolute; inset: 0; background-size: cover; background-position: center 22%; opacity: 0;
    transition: opacity .8s ease; animation: parasite-drift 24s ease-in-out infinite alternate; }
  .parasite-hero-art.on { opacity: 1; }
  .parasite-hero::before { content: ""; position: absolute; inset: 0; z-index: 1;
    background: linear-gradient(90deg, rgba(22, 14, 40, .92) 0%, rgba(60, 20, 90, .55) 55%, rgba(219, 39, 119, .25) 100%); }
  @keyframes parasite-drift { from { transform: scale(1.08); } to { transform: scale(1.14) translateX(-2%); } }
  .parasite-hero-body, .parasite-hero-last { position: relative; z-index: 2; }
  .parasite-hero-body { flex: 1; min-width: 0; }
  .parasite-hero small { display: block; opacity: .8; font-size: 12px; }
  .parasite-hero b { display: block; margin: 2px 0 8px; font: 700 24px "Spiegel", "Arial", sans-serif; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .parasite-hero b i { font-style: normal; font-weight: 400; opacity: .6; font-size: 17px; }
  .parasite-hero span { opacity: .9; font-size: 12px; }
  .parasite-hero-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .parasite-hero-cut { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 8px; font-size: 11.5px; }
  .parasite-cut { display: inline-flex; align-items: center; gap: 5px; }
  .parasite-cut::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--c); box-shadow: 0 0 8px var(--c); }
  .parasite-cut.gm { --c: #f87171; } .parasite-cut.ch { --c: #facc15; }
  .parasite-cut-need { padding: 2px 8px; border-radius: 99px; background: rgba(250, 204, 21, .16); color: #fde68a; font-weight: 600;
    opacity: 1 !important; }
  .parasite-chip { padding: 4px 10px; border-radius: 99px; font-size: 11.5px; font-weight: 600; opacity: 1 !important;
    background: rgba(255, 255, 255, .14); border: 1px solid rgba(255, 255, 255, .18); }
  .parasite-chip.rank { background: linear-gradient(135deg, rgba(167, 139, 250, .5), rgba(219, 39, 119, .45)); }
  .parasite-hero-last { flex: none; text-align: right; padding: 10px 14px; border-radius: 14px; background: rgba(10, 8, 18, .5);
    border: 1px solid rgba(255, 255, 255, .12); }
  .parasite-hero-last b { font-size: 16px; margin: 2px 0; }
  .parasite-hero-last span { display: block; font-size: 11.5px; }
  .parasite-hero-result { font-weight: 700; } .parasite-hero-result.win { color: #4ade80; } .parasite-hero-result.loss { color: #f87171; }
  /* Parasite's icons: a purple-to-pink gradient line */
  .parasite-hub-tab:not(.active) svg { stroke: url(#parasite-grad); filter: drop-shadow(0 0 5px rgba(167, 139, 250, .35)); }
  .parasite-hub-tab:active { transform: scale(.92); transition-duration: .06s; }
  /* Motion: cards rise in turn */
  @keyframes parasite-rise { from { opacity: 0; transform: translateY(10px) scale(.985); } }
  .parasite-hub-page.active > * { animation: parasite-rise .45s cubic-bezier(.2, .8, .2, 1) both; }
  .parasite-hub-page.active > *:nth-child(2) { animation-delay: .05s; } .parasite-hub-page.active > *:nth-child(3) { animation-delay: .1s; }
  .parasite-hub-page.active > *:nth-child(4) { animation-delay: .15s; } .parasite-hub-page.active > *:nth-child(5) { animation-delay: .2s; }
  .parasite-hub-page.active > *:nth-child(n+6) { animation-delay: .25s; }
  .parasite-skin-toggle::after { transition: left .3s cubic-bezier(.3, 1.6, .5, 1), background .15s; }
  #parasite-hub lol-uikit-flat-button:active { transform: scale(.96); }
  .parasite-hub-section, #parasite-hub .theme-settings-section { margin: 0 0 12px; padding: 14px 16px; border-radius: 14px;
    background: #211e2d; border: 1px solid transparent; }
  .parasite-hub-title, #parasite-hub .theme-settings-section-title { border-bottom: 0; padding-bottom: 0; margin-bottom: 10px;
    color: #a3a0ad; font: 600 11.5px "Spiegel", "Arial", sans-serif; letter-spacing: .5px; }
  .parasite-news { border-radius: 14px; border-color: #4b3f73; background: #2a2340; }
  .parasite-skin-row { border-radius: 12px; background: #1d1a29; border-color: transparent; transition: transform .15s, background .15s; }
  .parasite-skin-row:hover { transform: translateY(-2px); background: #262236; }
  .parasite-asset-row { border-radius: 12px; border-color: #2e2a3d; }
  .parasite-hub-advanced { border-top: 0; }
  .parasite-customize { display: flex; flex-direction: column; gap: 10px; padding: 4px 2px 8px; }
  .parasite-customize-row { display: grid; grid-template-columns: 1fr 36px 96px 80px; align-items: center; gap: 8px;
    color: #cdbe91; font: 13px "Beaufort for LOL", serif; }
  .parasite-customize-row input[type="color"] { width: 36px; height: 24px; padding: 0; border: 1px solid #785a28;
    background: none; cursor: pointer; }
  .parasite-customize-state { color: #a09b8c; font-size: 11px; }
`;
let parasiteHubTab = "status";
function closeParasiteHub() {
  document.getElementById("parasite-hub-backdrop")?.remove();
  document.querySelector("lol-uikit-navigation-item.menu_item_Golden")?.removeAttribute("active");
}
function openParasiteHub() {
  if (document.getElementById("parasite-hub-backdrop"))
    return;
  const backdrop = document.createElement("div");
  backdrop.id = "parasite-hub-backdrop";
  backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) closeParasiteHub();
  });
  const hub = document.createElement("div");
  hub.id = "parasite-hub";
  const side = document.createElement("div");
  side.className = "parasite-hub-side";
  const logo = document.createElement("div");
  logo.className = "parasite-hub-logo";
  logo.textContent = "L";
  side.appendChild(logo);
  const main = document.createElement("div");
  main.className = "parasite-hub-main";
  const close = document.createElement("div");
  close.className = "parasite-hub-close";
  close.textContent = "\\u00d7";
  close.title = parasiteTr("Close");
  close.addEventListener("click", closeParasiteHub);
  main.appendChild(close);
  // The page's title and Parasite's version above every tab
  const heading = document.createElement("div");
  heading.className = "parasite-hub-heading";
  const headingTitle = document.createElement("span");
  const version = document.createElement("span");
  version.className = "parasite-hub-version";
  heading.append(headingTitle, version);
  main.appendChild(heading);
  const select = async (tab) => {
    parasiteHubTab = tab.id;
    headingTitle.textContent = parasiteTr(tab.label);
    side.querySelectorAll(".parasite-hub-tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === tab.id));
    main.querySelectorAll(".parasite-hub-page").forEach((page) => page.classList.toggle("active", page.dataset.tab === tab.id));
    main.scrollTop = 0;
    const page = main.querySelector(`.parasite-hub-page[data-tab="${tab.id}"]`);
    if (page.dataset.rendered) return;
    page.dataset.rendered = "true";
    try {
      await tab.render(page);
    } catch (err) {
      error(`Parasite hub: ${tab.id} failed`, err);
    }
    if (tab.reload) {
      const reload = document.createElement("lol-uikit-flat-button");
      reload.className = "parasite-panel-reload";
      reload.textContent = parasiteTr("Reload client to apply");
      reload.addEventListener("click", () => window.restartClient());
      page.appendChild(reload);
    }
  };
  PARASITE_HUB_TABS.forEach((tab) => {
    const item = document.createElement("div");
    item.className = "parasite-hub-tab";
    item.dataset.tab = tab.id;
    item.innerHTML = parasiteHubIcon(tab.icon);
    item.dataset.label = parasiteTr(tab.label);
    item.addEventListener("click", () => select(tab));
    side.appendChild(item);
    const page = document.createElement("div");
    page.className = "parasite-hub-page";
    page.dataset.tab = tab.id;
    main.appendChild(page);
  });
  fetch("//plugins/PARASITE-News/whats-new.json").then((r) => r.json()).then((news) => {
    version.textContent = `Parasite ${news.version}`;
  }).catch(() => {});
  hub.append(side, main);
  backdrop.appendChild(hub);
  document.body.appendChild(backdrop);
  document.querySelector("lol-uikit-navigation-item.menu_item_Golden")?.setAttribute("active", "true");
  select(PARASITE_HUB_TABS.find((tab) => tab.id === parasiteHubTab) || PARASITE_HUB_TABS[0]);
}
// Rose's panel, now opened only for core settings: drop its Discord and Ko-Fi links.
function cleanRosePanel(panel) {
  const links = panel.querySelector(".settings-links");
  if (!links) return false;
  links.querySelectorAll("a").forEach((link) => {
    if (/discord\\.com|ko-fi\\.com/.test(link.href)) link.remove();
  });
  return true;
}
function mountParasiteHub() {
  window.parasiteOpenHub = openParasiteHub;
  const style = document.createElement("style");
  style.textContent = PARASITE_PANEL_CSS;
  document.head.appendChild(style);
  const defs = document.createElement("div");
  defs.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  defs.innerHTML = '<svg width="0" height="0" aria-hidden="true"><defs><linearGradient id="parasite-grad" x1="0" y1="0" x2="1" y2="1">'
    + '<stop offset="0" stop-color="#c4b5fd"/><stop offset=".55" stop-color="#a78bfa"/><stop offset="1" stop-color="#f472b6"/>'
    + '</linearGradient></defs></svg>';
  document.body.appendChild(defs);
  // A click on PARASITE opens the hub. Caught on the way down, before PARASITE-UI's own
  // listener on the nav item; with Rose's panel open the click goes through to close it.
  document.addEventListener("click", (event) => {
    const navItem = event.target.closest && event.target.closest("lol-uikit-navigation-item.menu_item_Golden");
    if (!navItem || document.getElementById("parasite-settings-panel")) return;
    event.stopPropagation();
    event.preventDefault();
    if (document.getElementById("parasite-hub-backdrop")) closeParasiteHub();
    else openParasiteHub();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.getElementById("parasite-hub-backdrop")) closeParasiteHub();
  });
  new MutationObserver(() => {
    const panel = document.getElementById("parasite-settings-panel");
    if (!panel || panel.dataset.parasiteCleaned) return;
    panel.dataset.parasiteCleaned = "true";
    let tries = 0;
    const attempt = () => {
      if (document.body.contains(panel) && !cleanRosePanel(panel) && ++tries < 40) setTimeout(attempt, 100);
    };
    attempt();
  }).observe(document.body, { childList: true });
}
'''


def checkbox(locale, element_id, key):
    """A settings checkbox exactly as the theme builds it, for removing it."""
    return f'''      UI.createCheckBox(
        `${{await getString("theme-settings.{locale}")}}`,
        "{element_id}",
        "{element_id}box",
        () => {{
          restartAfterChange("{element_id}", "{key}");
        }},
        true,
        "{key}"
      ),
'''


# (file, old, new): exact replacements applied before renaming. Each must match.
PATCHES = [
    # Settings move from the client settings window into the Parasite panel.
    ("index.js",
     'function Settings(context) {\n  ElainaData.set("settingsChangenumber", 0);\n  settingsUtils(context, structure);\n}\n',
     PARASITE_PANEL_JS),
    # The play button, Find Match and the queue card keep League's own colors.
    ("config/filters.js", '"PlayButton"        : "sepia(1) sepia(1) sepia(1)",',
     '"PlayButton"        : "none",'),
    ("config/filters.js", '"find-match-button" : "sepia(1) sepia(1) sepia(1)",',
     '"find-match-button" : "none",'),
    ("config/filters.js", '"PartiesStatusCard" : "sepia(1) sepia(1)",',
     '"PartiesStatusCard" : "none",'),
    ("assets/styles/themes/rcp-fe-lol-parties.css",
     ".parties-game-search-info {\n\tcolor:#000000!important\n}\n\n"
     ".parties-game-search-elapsed {\n\tcolor: white!important;\n"
     "\ttext-shadow: -1px 0 black, 0 1px black, 1px 0 black, 0 -1px black !important;\n}\n", ""),
    ("assets/styles/themes/rcp-fe-lol-parties.css",
     ".parties-status-card-bg-container video {\n"
     "\tfilter: saturate(0.5) brightness(1) invert(1) hue-rotate(27deg) !important;\n}\n", ""),
    ("assets/styles/themes/rcp-fe-lol-parties.css",
     ":host .parties-status-card.open {\n\tfilter: hue-rotate(240deg) !important;\n}\n", ""),
    # Champ select keeps the text above the timer (contrast(0) made it vanish) and
    # League's own lock-in button.
    ("assets/styles/themes/rcp-fe-lol-parties.css",
     ".champion-select .timer-status::before {\n\tfilter: contrast(0) brightness(1) !important;\n}\n\n"
     ".champion-select .action-button-container::after {\n\tfilter: sepia(1) !important;\n}\n", ""),
    # No loot helper (bulk open / disenchant buttons in the loot tab).
    ("index.js", '    if (ElainaData$1.get("loot-helper"))\n      lootHelper.main();', '    if (false)\n      lootHelper.main();'),
    ("index.js",
     '''    UI.createRow("loothelp", [
      UI.createCheckBox(
        `${await getString("plugins-settings.loot-helper")}`,
        "lh",
        "lhbox",
        () => {
          restartAfterChange("lh", "loot-helper");
        },
        true,
        "loot-helper"
      )
    ]),
''', ""),
    ("config/datastoreDefault.js", '"loot-helper"                   : true,', '"loot-helper"                   : false,'),
    # League's own fonts in the client: the theme's font is off by default, and turned
    # off once for players who had it on from an earlier default (they can turn it on again)
    ("config/datastoreDefault.js", '"Custom-Font"                   : true,', '"Custom-Font"                   : false,'),
    ("index.js",
     '  customFont = () => {\n    document.getElementById("Custom-font")?.remove();\n    if (!ElainaData.get("Custom-Font")) {\n',
     '  customFont = () => {\n    document.getElementById("Custom-font")?.remove();\n'
     '    if (!ElainaData.get("parasite-default-font-reset")) {\n'
     '      ElainaData.set("parasite-default-font-reset", true);\n'
     '      ElainaData.set("Custom-Font", false);\n'
     '    }\n'
     '    if (!ElainaData.get("Custom-Font")) {\n'),
    # The profile page shows its background splash (the hub's Profile background page picks
    # it): shown by default, and shown once for players who had it hidden from the old default
    ("config/datastoreDefault.js", '"hide-profile-background"       : true,',
     '"hide-profile-background"       : false,'),
    ("index.js",
     '  componentsCss = () => {\n    let cssImports = "";\n',
     '  componentsCss = () => {\n    let cssImports = "";\n'
     '    if (!ElainaData.get("parasite-profile-background-shown")) {\n'
     '      ElainaData.set("parasite-profile-background-shown", true);\n'
     '      ElainaData.set("hide-profile-background", false);\n'
     '    }\n'),
    # League's own game mode icons in the play menu (the theme's recoloured ones are off by
    # default, and off once for players who had them on; they can turn them on again)
    ("config/datastoreDefault.js", '"Custom-Gamemode-Icon"\t\t\t: true,', '"Custom-Gamemode-Icon"\t\t\t: false,'),
    ("index.js",
     '      ElainaData.set("hide-profile-background", false);\n    }\n',
     '      ElainaData.set("hide-profile-background", false);\n    }\n'
     '    if (!ElainaData.get("parasite-gamemode-icons-reset")) {\n'
     '      ElainaData.set("parasite-gamemode-icons-reset", true);\n'
     '      ElainaData.set("Custom-Gamemode-Icon", false);\n'
     '    }\n'),
    # League's own status icons in the friend list: a flat green fill turned the round
    # masked online icon into a square, and position:relative moved it
    ("assets/styles/themes/rcp-fe-viewport-sidebar.css",
     ".availability-icon {\n\tposition: relative!important;\n}\n\n"
     ".availability-icon.chat {\n\tbackground: #09a646 !important;\n}\n\n", ""),
    # Parasite updates the theme itself: no Elaina changelog or update popup.
    ("index.js", "    const checkUpdate = new CheckUpdate();\n    checkUpdate.main();\n", ""),
    # ...nor the popup's styles: their bare ".message" rule also moved League's champ
    # select text above the timer ("Game starting", "Pick your champion") off its place.
    ("assets/styles/themes/elaina.css", '@import url("./theme-update-message.css");\n', ""),
    # No automation that plays for the player: auto find queue and honor skip.
    ("index.js", "  AutoQueue(context);\n  skipHonor(context);\n", ""),
    # The hub goes up right after the theme's storage, before the steps that read files
    # and load the theme data: when one of those was slow or failed, the hub was never
    # mounted and the PARASITE tab opened Rose's settings panel instead.
    ("index.js",
     '  await restoreDefaultDataStore();\n  ElainaData$1.set("start-time", Date.now());\n'
     '  log("Initializing file system for theme");\n  await fileSystem.init(context);\n'
     '  log("Initializing icon sync storage");\n  await syncUserIcons.init();\n'
     '  log("Initializing theme");\n  await initThemeDataCdn();\n  initDebug();\n'
     '  Settings(context);\n  transparentLobby(context);\n}\n',
     '  try {\n    await restoreDefaultDataStore();\n  } catch (err) {\n    error("Theme init: default data failed", err);\n  }\n'
     '  ElainaData$1.set("start-time", Date.now());\n'
     '  try {\n    Settings(context);\n  } catch (err) {\n    error("Parasite hub failed to mount", err);\n  }\n'
     '  for (const [name, step] of [\n'
     '    ["file system", () => fileSystem.init(context)],\n'
     '    ["icon sync storage", () => syncUserIcons.init()],\n'
     '    ["theme data", () => initThemeDataCdn()]\n'
     '  ]) {\n'
     '    log(`Initializing ${name}`);\n'
     '    try {\n      await step();\n    } catch (err) {\n      error(`Theme init: ${name} failed`, err);\n    }\n  }\n'
     '  initDebug();\n  transparentLobby(context);\n}\n'),
    ("index.js", "        await queueSection(),\n", ""),
    # No fake mastery score or rank sent to friends.
    ("index.js",
     '      if (ElainaData.get("Custom-mastery-score"))\n        customProfile.customMasteryScore();\n', ""),
    ("index.js",
     '      if (ElainaData.get("Custom-rank")) {\n        window.setTimeout(async () => {\n'
     '          customProfile.customRank();\n          window.customRank = customProfile.customRank;\n'
     '        }, 1e4);\n      }\n', ""),
    # Turkish (parasite/theme/locales/tr-TR.js), and "Follow client language" follows
    # the language picked in Parasite's panel, which Parasite's own menus use too.
    ("index.js", '    { label: "中文", value: "zh-CN" }\n  ];',
     '    { label: "中文", value: "zh-CN" },\n    { label: "Türkçe", value: "tr-TR" }\n  ];'),
    ("index.js",
     '  if (selectedLang && selectedLang !== "client")\n    return selectedLang;\n  return getClientLocale();',
     '  if (selectedLang && selectedLang !== "client")\n    return selectedLang;\n'
     '  const parasiteLanguage = window.ParasiteI18n && window.ParasiteI18n.language;\n'
     '  if (parasiteLanguage) {\n'
     '    const locales = { tr: "tr-TR", ru: "ru-RU", vi: "vi-VN", zh: "zh-CN" };\n'
     '    return locales[parasiteLanguage.slice(0, 2)] || "default";\n'
     '  }\n'
     '  return getClientLocale();'),
    # Name colors come from the CUSTOMIZE tab now, League's own until a player picks one.
    ("index.js",
     '    if (ElainaData.get("change-nickname-color"))\n      addCss.customNicknameColor();',
     '    if (false)\n      addCss.customNicknameColor();'),
    # No "Invite all" button or friend-group dropdown in the lobby.
    ("index.js",
     '    if (ElainaData$1.get("Enable-Invite-Fr"))\n      inviteAllFriends.main();',
     '    if (false)\n      inviteAllFriends.main();'),
    ("index.js",
     '''    br(),
    UI.createCheckBox(
      `${await getString("plugins-settings.enable-invite-fr")}`,
      "invfr",
      "invfrbox",
      () => {
        restartAfterChange("invfr", "Enable-Invite-Fr");
      },
      true,
      "Enable-Invite-Fr"
    )
  ]);''', "  ]);"),
    ("config/datastoreDefault.js", '"Enable-Invite-Fr"              : true,',
     '"Enable-Invite-Fr"              : false,'),
    # Appearing offline is Parasite Offline's job (the chat proxy), not the status dot.
    ("index.js", "    const offlineMode = new OfflineMode();\n    offlineMode.main();\n", ""),
    # The gear opens the client settings directly, not the theme's own menu first.
    ("index.js",
     '    if (ElainaData.get("Old-League-Loader-Settings")) {\n      while (!manager())',
     '    if (false) {\n      while (!manager())'),
    ("index.js",
     '''    UI.createCheckBox(
      `${await getString("plugins-settings.old-ll-settings")}`,
      "oldll",
      "oldllbox",
      () => {
        restartAfterChange("oldll", "Old-League-Loader-Settings");
      },
      true,
      "Old-League-Loader-Settings"
    ),
    br(),
''', ""),
    # Honor, trophy, emblem, ticker and hover card show the client's own art.
    ("index.js",
     'key: "Custom-Emblem",\n          css: "emblem.css",',
     'key: "Custom-Emblem",\n          css: "null.css",'),
    ("index.js",
     'key: "Custom-Ticker",\n          css: "ticker.css",',
     'key: "Custom-Ticker",\n          css: "null.css",'),
    ("index.js",
     'key: "Custom-Trophy",\n          css: "trophy.css",',
     'key: "Custom-Trophy",\n          css: "null.css",'),
    # Loading spinners and loading screens are League's own: no Kai'Sa picture anywhere
    ("index.js",
     'key: "Custom-Loading-Icon",\n          css: "loadingIcon.css",',
     'key: "Custom-Loading-Icon",\n          css: "null.css",'),
    ("index.js",
     'key: "animate-loading",\n          css: "animate-loading-screen.css",\n          altCss: "static-loading-screen.css"',
     'key: "animate-loading",\n          css: "null.css",\n          altCss: "null.css"'),
    ("index.js",
     'let loadingIcon = storeDoc.querySelector(".store-app-wrapper > .loading-spinner");',
     'let loadingIcon = null;'),
    ("index.js", '    loadingImage.style.content = "var(--Loading)";\n', ''),
    ("index.js",
     "    const customTickerIcon = new CustomTickerIcon();\n    customTickerIcon.main();\n", ""),
    ("index.js",
     '    if (ElainaData.get("Custom-Hover-card-backdrop")) {\n      const customHoverCardBackdrop',
     '    if (false) {\n      const customHoverCardBackdrop'),
    ("index.js",
     '    if (ElainaData.get("Custom-Emblem")) {\n      const customEmblemIcon',
     '    if (false) {\n      const customEmblemIcon'),
    ("index.js", checkbox("custom-emblem", "cusemi", "Custom-Emblem") + "      br(),\n", ""),
    ("index.js", checkbox("custom-trophy", "custrophy", "Custom-Trophy") + "      br(),\n", ""),
    ("index.js", checkbox("custom-ticker", "custick", "Custom-Ticker") + "      br()\n", ""),
    ("index.js", checkbox("custom-hover-card-backdrop", "cushvbdrop", "Custom-Hover-card-backdrop"), ""),
    ("config/datastoreDefault.js", '"Custom-Hover-card-backdrop"\t: true,',
     '"Custom-Hover-card-backdrop"\t: false,'),
    ("config/datastoreDefault.js", '"Custom-Emblem"                 : true,',
     '"Custom-Emblem"                 : false,'),
    ("config/datastoreDefault.js", '"Custom-Trophy"                 : true,',
     '"Custom-Trophy"                 : false,'),
    ("config/datastoreDefault.js", '"Custom-Ticker"                 : true,',
     '"Custom-Ticker"                 : false,'),
    # Default wallpaper/audio are Parasite's own files.
    ("index.js",
     '"Wallpaper-list": ["elaina1.webm", "elaina2.jpg"],',
     '"Wallpaper-list": ["parasite-wallpaper.webm", "parasite-dark.jpg", "parasite-wallpaper.jpg"],'),
    ("index.js",
     '"Audio-list": ["Laur - その花は世界を紡ぐ.flac", "Laur - Mellifluous.flac"],',
     '"Audio-list": ["parasite-silence.wav"],'),
    # Fill the window with wallpapers of any aspect ratio instead of letterboxing.
    ("assets/styles/themes/theme-wallpapers.css",
     "#elaina-bg {\n\twidth:100%;\n\theight: 100%;\n",
     "#elaina-bg {\n\twidth:100%;\n\theight: 100%;\n\tobject-fit: cover;\n"),
    # A picture wallpaper is stretched to the client left of the friends list (225px): all of it
    # shows, nothing is cut off, and it is stretched less than across the whole window
    ("assets/styles/themes/theme-wallpapers.css",
     "#elaina-static-bg {\n\twidth:100%;\n",
     "#elaina-static-bg {\n\twidth: calc(100% - 225px);\n\theight: 100%;\n\tobject-fit: fill;\n\timage-rendering: auto;\n"),
    # No button that hides the top-right nav icons.
    ("index.js",
     'if (ElainaData.get("enable-hide-top-navbar-friendlist-button")) {\n      hideTopNavbarButton.addHideButton();',
     'if (false) {\n      hideTopNavbarButton.addHideButton();'),
    ("config/datastoreDefault.js",
     '"enable-hide-top-navbar-friendlist-button" : true,',
     '"enable-hide-top-navbar-friendlist-button" : false,'),
    # RP and Blue Essence keep League's own icons, whatever was saved before.
    ("index.js",
     'key: "Custom-RP-Icon",\n          css: "riotpoint.css",',
     'key: "Custom-RP-Icon",\n          css: "null.css",'),
    ("index.js",
     'key: "Custom-BE-Icon",\n          css: "blueessence.css",',
     'key: "Custom-BE-Icon",\n          css: "null.css",'),
    ("index.js",
     '''      UI.createCheckBox(
        `${await getString("theme-settings.custom-rp-icon")}`,
        "cusrpi",
        "cusrpibox",
        () => {
          restartAfterChange("cusrpi", "Custom-RP-Icon");
        },
        true,
        "Custom-RP-Icon"
      ),
      br(),
      UI.createCheckBox(
        `${await getString("theme-settings.custom-be-icon")}`,
        "cusbei",
        "cusbeibox",
        () => {
          restartAfterChange("cusbei", "Custom-BE-Icon");
        },
        true,
        "Custom-BE-Icon"
      ),
      br(),
''', ""),
    # The profile shows the real rank emblem, rank name and banner.
    ("index.js",
     'key: "Custom-Clash-banner",\n          css: "clashbanner.css",',
     'key: "Custom-Clash-banner",\n          css: "null.css",'),
    ("index.js",
     'key: "Custom-Rank-Icon",\n          css: "rank.css",',
     'key: "Custom-Rank-Icon",\n          css: "null.css",'),
    ("index.js",
     '''      UI.createCheckBox(
        `${await getString("theme-settings.custom-rank-icon")}`,
        "cusranki",
        "cusrankibox",
        () => {
          restartAfterChange("cusranki", "Custom-Rank-Icon");
        },
        true,
        "Custom-Rank-Icon"
      ),
      br(),
''', ""),
    ("index.js",
     '''      UI.createCheckBox(
        `${await getString("theme-settings.custom-clash-banner")}`,
        "cusclassb",
        "cusclassbbox",
        () => {
          restartAfterChange("cusclassb", "Custom-Clash-banner");
        },
        true,
        "Custom-Clash-banner"
      ),
      br(),
''', ""),
    ("index.js",
     '    if (ElainaData.get("custom-rank-name"))\n      customProfile.CustomProfileRankName();',
     '    if (false)\n      customProfile.CustomProfileRankName();'),
    ("index.js",
     '''    UI.createCheckBox(
      `${await getString("theme-settings.custom-rank-name")}`,
      "cusrankname",
      "cusranknamebox",
      () => {
        restartAfterChange("cusrankname", "custom-rank-name");
      },
      true,
      "custom-rank-name"
    ),
    br(),
    UI.createSearchBox("Rank-line1"),
    UI.createSearchBox("Rank-line2"),
    br(),
''', ""),
    # Real summoner icon, border and regalia banner.
    ("index.js",
     'key: "Custom-Avatar",\n          css: "avatar.css",',
     'key: "Custom-Avatar",\n          css: "null.css",'),
    ("index.js",
     '    if (ElainaData.get("Custom-Avatar")) {\n      customAvatar.main();',
     '    if (false) {\n      customAvatar.main();'),
    ("index.js",
     '    if (ElainaData.get("Custom-Border")) {\n      const customBorder',
     '    if (false) {\n      const customBorder'),
    ("index.js",
     '    if (ElainaData.get("Custom-Regalia-Banner")) {\n      const customBanner',
     '    if (false) {\n      const customBanner'),
    ("index.js",
     '''      UI.createCheckBox(
        `${await getString("theme-settings.custom-avatar")}`,
        "cusav",
        "cusavbox",
        () => {
          restartAfterChange("cusav", "Custom-Avatar");
        },
        true,
        "Custom-Avatar"
      ),
      br(),
      UI.createCheckBox(
        `${await getString("theme-settings.custom-border")}`,
        "cusbor",
        "cusborbox",
        () => {
          restartAfterChange("cusbor", "Custom-Border");
        },
        true,
        "Custom-Border"
      ),
      br(),
      UI.createCheckBox(
        `${await getString("theme-settings.custom-regalia-banner")}`,
        "cusregabnr",
        "cusregabnrbox",
        () => {
          restartAfterChange("cusregabnr", "Custom-Regalia-Banner");
        },
        true,
        "Custom-Regalia-Banner"
      ),
      br(),
      UI.createRow("Custom-banner-row", [
        createBannerDropdown()
      ]),
''', ""),
    ("config/datastoreDefault.js", '"Custom-Avatar"                 : true,',
     '"Custom-Avatar"                 : false,'),
    ("config/datastoreDefault.js", '"Custom-Border"\t                : true,',
     '"Custom-Border"\t                : false,'),
    ("config/datastoreDefault.js", '"Custom-Regalia-Banner"         : true,',
     '"Custom-Regalia-Banner"         : false,'),
    ("config/datastoreDefault.js", '"custom-rank-name"              : true,',
     '"custom-rank-name"              : false,'),
    ("config/datastoreDefault.js", '"Custom-Rank-Icon"              : true,',
     '"Custom-Rank-Icon"              : false,'),
    ("config/datastoreDefault.js", '"Custom-Clash-banner"\t\t\t: true,',
     '"Custom-Clash-banner"\t\t\t: false,'),
    ("config/datastoreDefault.js", '"Custom-RP-Icon"                : true,',
     '"Custom-RP-Icon"                : false,'),
    ("config/datastoreDefault.js", '"Custom-BE-Icon"                : true,',
     '"Custom-BE-Icon"                : false,'),
    # Saved wallpaper lists still get Parasite's default wallpapers.
    ("index.js",
     '  setDefaultData(defaultData, false);\n}',
     '  setDefaultData(defaultData, false);\n'
     '  const wallpapers = ElainaData.get("Wallpaper-list") || [];\n'
     '  for (const name of defaultData["Wallpaper-list"]) {\n'
     '    if (!wallpapers.includes(name)) wallpapers.push(name);\n'
     '  }\n'
     '  ElainaData.set("Wallpaper-list", wallpapers);\n'
     '  if (!ElainaData.has("parasite-league-background"))\n'
     '    ElainaData.set("parasite-league-background", true);\n'
     '  document.documentElement.classList.toggle("parasite-league-bg", !!ElainaData.get("parasite-league-background"));\n}'),
    # League's own background is the default: no theme wallpaper, no window effect, and
    # the rules that hide League's backgrounds only apply while a theme wallpaper is on.
    # A wallpaper is picked from the hub's Wallpaper page (the checkbox below).
    ("config/datastoreDefault.js",
     '"disable-theme-wallpaper"       : false,',
     '"disable-theme-wallpaper"       : false,\n\t"parasite-league-background"        : true,'),
    ("index.js",
     '    if (ElainaData.get("disable-theme-wallpaper"))\n      wallpaperControls.style.display = "none";',
     '    if (ElainaData.get("disable-theme-wallpaper") || ElainaData.get("parasite-league-background"))\n'
     '      wallpaperControls.style.display = "none";'),
    ("index.js",
     '  setWallpaperElement = () => {\n    if (!ElainaData.get("disable-theme-wallpaper")) {',
     '  setWallpaperElement = () => {\n'
     '    if (!ElainaData.get("disable-theme-wallpaper") && !ElainaData.get("parasite-league-background")) {'),
    ("index.js",
     '  setImageWallpaperElement = () => {\n    if (!ElainaData.get("disable-theme-wallpaper")) {',
     '  setImageWallpaperElement = () => {\n'
     '    if (!ElainaData.get("disable-theme-wallpaper") && !ElainaData.get("parasite-league-background")) {'),
    ("index.js",
     '    if (!ElainaData.get("disable-theme-wallpaper")) {\n      window.Effect.clear();',
     '    if (!ElainaData.get("disable-theme-wallpaper") || ElainaData.get("parasite-league-background")) {\n'
     '      window.Effect.clear();'),
    ("index.js",
     '  return UI.createSection("theme-settings-wallpaper", await getString("theme-settings.settings-section-wallpaper"), [\n',
     '  return UI.createSection("theme-settings-wallpaper", await getString("theme-settings.settings-section-wallpaper"), [\n'
     '    UI.createCheckBox(\n'
     '      parasiteTr("Use League\'s own background"),\n'
     '      "parasiteleaguebg",\n'
     '      "parasiteleaguebgbox",\n'
     '      () => {\n'
     '        const on = !!ElainaData.get("parasite-league-background");\n'
     '        document.documentElement.classList.toggle("parasite-league-bg", on);\n'
     '        const controls = document.querySelector(".wallpaper-controls");\n'
     '        const video = document.getElementById("elaina-bg");\n'
     '        const imgWallpaper = document.getElementById("elaina-static-bg");\n'
     '        if (!on && !ElainaData.get("disable-theme-wallpaper")) {\n'
     '          setWallpaper();\n'
     '          setImageWallpaper();\n'
     '          wallpaperPlayPause();\n'
     '          if (controls)\n'
     '            controls.style.display = "flex";\n'
     '        } else {\n'
     '          if (video)\n'
     '            video.src = "";\n'
     '          if (imgWallpaper)\n'
     '            imgWallpaper.src = "";\n'
     '          if (controls)\n'
     '            controls.style.display = "none";\n'
     '        }\n'
     '        applyWindowEffect();\n'
     '      },\n'
     '      true,\n'
     '      "parasite-league-background"\n'
     '    ),\n'),
    ("assets/styles/themes/elaina.css", "\n#background-ambient {\n", "\nhtml:not(.parasite-league-bg) #background-ambient {\n"),
    ("assets/styles/themes/elaina.css", "\n.store-backdrop {\n", "\nhtml:not(.parasite-league-bg) .store-backdrop {\n"),
    ("assets/styles/themes/elaina.css", "\n.background {\n", "\nhtml:not(.parasite-league-bg) .background {\n"),
    ("assets/styles/themes/elaina.css", "\n.rcp-fe-lol-game-in-progress {\n", "\nhtml:not(.parasite-league-bg) .rcp-fe-lol-game-in-progress {\n"),
    ("assets/styles/themes/elaina.css", "\n.loading-tab::after {\n", "\nhtml:not(.parasite-league-bg) .loading-tab::after {\n"),
    ("assets/styles/themes/elaina.css", "\n.yourshop-root {\n", "\nhtml:not(.parasite-league-bg) .yourshop-root {\n"),
    ("assets/styles/themes/elaina.css", "\n.npe-root-component {\n", "\nhtml:not(.parasite-league-bg) .npe-root-component {\n"),
    ("assets/styles/themes/elaina.css", "\ndiv > div > .rcp-fe-lol-tft-application-background {\n", "\nhtml:not(.parasite-league-bg) div > div > .rcp-fe-lol-tft-application-background {\n"),
    ("assets/styles/themes/rcp-fe-lol-parties.css",
     "\n.parties-background.ember-view .lol-uikit-background-switcher-image {",
     "\nhtml:not(.parasite-league-bg) .parties-background.ember-view .lol-uikit-background-switcher-image {"),
    ("assets/styles/themes/rcp-fe-lol-parties.css", "\n.parties-background {",
     "\nhtml:not(.parasite-league-bg) .parties-background {"),
    ("assets/styles/components/lobby-transparent-filter.css", ".parties-view .parties-background {",
     "html:not(.parasite-league-bg) .parties-view .parties-background {"),
    # The real summoner level shows instead of a custom one.
    ("index.js",
     '      if (ElainaData$1.get("custom-summoner-lv"))\n        customSummonerLv.main();',
     '      if (false)\n        customSummonerLv.main();'),
    ("index.js",
     '''    UI.createCheckBox(
      `${await getString("theme-settings.custom-summoner-lv")}`,
      "cussumlv",
      "cussumlvbox",
      () => {
        restartAfterChange("cussumlv", "custom-summoner-lv");
      },
      true,
      "custom-summoner-lv"
    ),
    br(),
    UI.createSearchBox("custom-summoner-lv-number"),
    br(),
''', ""),
    ("config/datastoreDefault.js", '"custom-summoner-lv"            : true,',
     '"custom-summoner-lv"            : false,'),
    # "+" next to the wallpaper pause button: opens the wallpapers folder, then
    # takes the pasted file's name (Pengu 1.1.6 can't list folders) and adds it.
    ("index.js", "    pauseBg.append(pauseBgIcon);\n    progressBar.append(progress);\n",
     "    pauseBg.append(pauseBgIcon);\n" + ADD_WALLPAPER_JS + "    progressBar.append(progress);\n"),
    ("index.js", "      newBgChange.append(bgDropdown);\n",
     "      const sizeHint = document.createElement(\"div\");\n"
     "      sizeHint.id = \"bg-size-hint\";\n"
     "      sizeHint.textContent = parasiteTr(\"16:9 Size Preferred\");\n"
     "      newBgChange.append(bgDropdown, sizeHint);\n"),
    ("assets/styles/themes/theme-background-controllers.css", "#pause-bg:hover {",
     ADD_WALLPAPER_CSS + "#pause-bg:hover {"),
    # Cloud backup went to Elaina's server: hide that part of the backup tab.
    ("index.js",
     "const cloud = await cloudBackupSection();",
     "const cloud = { elements: [], postSetup: async () => {} };"),
    # Easter egg that opens Elaina's server.
    ("index.js",
     '          window.open(`${ElainaData.get("Elaina-domain-server")}elaina_nsfw/easteregg1`, "_blank");\n',
     ""),
    # NSFW toggle only drove Elaina's counter and easter egg.
    ("index.js",
     'async function nsfwSection() {\n  return UI.createCheckBox(',
     'async function nsfwSection() {\n  return document.createElement("div");\n  return UI.createCheckBox('),
    # Links to Elaina's repo point at Parasite.
    ("index.js",
     "https://github.com/Elaina69/Elaina-V4/releases/tag/v${cdn.version}",
     REPO_URL + "/releases"),
    ("index.js", "https://github.com/Elaina69/Elaina-V4/releases", REPO_URL + "/releases"),
    ("index.js", '"ElainaV4",\n          "https://github.com/Elaina69/Elaina-V4",',
     '"Parasite",\n          "' + REPO_URL + '",'),
    # Default settings.
    ("config/datastoreDefault.js", '"Rank-line1"                    : "Apprentice",',
     '"Rank-line1"                    : "Daughter of",'),
    ("config/datastoreDefault.js", '"Rank-line2"                    : "Witch",',
     '"Rank-line2"                    : "the Void",'),
    ("config/datastoreDefault.js", '"CurrentFont"                   : "elaina-herculanum_roman.ttf",',
     '"CurrentFont"                   : "beaufortforlol-bold.ttf",'),
    ("config/datastoreDefault.js",
     '\t\t"aegirseaborn.ttf",\n\t\t"elaina-herculanum_roman.ttf",\n\t\t"minecraftregular-bmg3.otf",\n\t\t"roboto-medium.ttf"',
     '\t\t"beaufortforlol-bold.ttf",\n\t\t"roboto-medium.ttf"'),
    ("config/datastoreDefault.js", '"nickname-color"                : "#f2c1d0",',
     '"nickname-color"                : "#b48cff",'),
    ("config/datastoreDefault.js", '"nickname-color-with-opacity"   : "#f2c1d0ff",',
     '"nickname-color-with-opacity"   : "#b48cffff",'),
    ("config/datastoreDefault.js", '"disable-theme-audio"           : false,',
     '"disable-theme-audio"           : true,'),
    ("config/datastoreDefault.js", '"holiday-message"               : true,',
     '"holiday-message"               : false,'),
    ("config/datastoreDefault.js", '"sync-user-icons"               : true,',
     '"sync-user-icons"               : false,'),
    ("config/datastoreDefault.js", '"Runes-BG"                      : true,',
     '"Runes-BG"                      : false,'),
    # These PUT fake values to /lol-chat/v1/me, which friends see.
    ("config/datastoreDefault.js", '"Custom-mastery-score"          : true,',
     '"Custom-mastery-score"          : false,'),
    ("config/datastoreDefault.js", '"Custom-rank"                   : true,',
     '"Custom-rank"                   : false,'),
    ("config/datastoreDefault.js", '"Custom-challenge-crystal"      : true,',
     '"Custom-challenge-crystal"      : false,'),
    ("config/icons.js", '"animation-logo.gif"', '"animation-logo.png"'),
    ("config/icons.js", '"loading.gif"', '"loading.png"'),
    ("config/icons.js", '"avatar.gif"', '"avatar.png"'),
]

# Names that must not go through the plain Elaina -> Parasite rename.
PRE_RENAMES = [
    (re.compile(r"https://github\.com/Elaina69\b[\w./-]*"), REPO_URL),
    (re.compile(r"Elaina Da Catto"), "Parasite"),
    (re.compile(r"elaina ?da ?catto", re.I), "parasite"),
    (re.compile(r"Elaina69"), "lustmyself"),
    (re.compile(r"elaina[-_]?v[24]", re.I), "Parasite"),
]


def match_case(word, repl):
    if word.isupper():
        return repl.upper()
    if word[0].isupper():
        return repl.capitalize()
    return repl.lower()


def rename(text):
    for pattern, repl in PRE_RENAMES:
        text = pattern.sub(repl, text)
    return re.sub(r"elaina", lambda m: match_case(m.group(0), "parasite"), text, flags=re.I)


ASSET_LIBRARY_JS = '''// Parasite: the asset library shows each folder's files (Parasite lists them over the
// bridge, since Pengu 1.1.6 plugins can't), Add opens the folder, x deletes a file,
// and files dropped on a row are copied into its folder.
const PARASITE_ASSET_CHUNK = 512 * 1024;
// Past this size an upload takes a while: say so, and show how far it got
const PARASITE_BIG_FILE = 50 * 1024 * 1024;
function parasiteAddingText(file, done = 0) {
  const text = parasiteTr("Adding {name}...", { name: file.name });
  if (file.size < PARASITE_BIG_FILE) return text;
  return `${text} ${Math.floor(done * 100)}% - ${parasiteTr("Large package, this can take a while")}`;
}
const parasiteAssetWaiters = new Map();
let parasiteAssetRequests = 0;
let parasiteAssetsSubscribed = false;
function parasiteAssets(kind, action, extra = {}) {
  const bridge = window.__parasiteBridge;
  if (!bridge) return Promise.resolve({ error: parasiteTr("Parasite isn't connected"), files: null });
  if (!parasiteAssetsSubscribed) {
    parasiteAssetsSubscribed = true;
    bridge.subscribe("parasite-assets", (reply) => {
      const waiter = parasiteAssetWaiters.get(reply && reply.requestId);
      if (waiter) {
        parasiteAssetWaiters.delete(reply.requestId);
        waiter(reply);
      }
    });
  }
  const requestId = `${Date.now()}-${++parasiteAssetRequests}`;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      parasiteAssetWaiters.delete(requestId);
      resolve({ error: parasiteTr("Parasite didn't answer"), files: null });
    }, 15000);
    parasiteAssetWaiters.set(requestId, (reply) => {
      clearTimeout(timer);
      resolve(reply);
    });
    bridge.send({ type: "parasite-assets", kind, action, requestId, ...extra });
  });
}
function parasiteBlobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
async function uploadParasiteAsset(kind, file, onProgress = () => {}) {
  const total = Math.max(1, Math.ceil(file.size / PARASITE_ASSET_CHUNK));
  for (let index = 0; index < total; index++) {
    const data = await parasiteBlobToBase64(file.slice(index * PARASITE_ASSET_CHUNK, (index + 1) * PARASITE_ASSET_CHUNK));
    const reply = await parasiteAssets(kind, "save", { name: file.name, index, total, data });
    if (reply.error) return reply;
    onProgress((index + 1) / total);
  }
  return parasiteAssets(kind, "list");
}
// Keeps the theme's list in the folder's order of discovery: known files first.
function syncParasiteAssetList(dataKey, files) {
  const current = ElainaData.get(dataKey) || [];
  const next = current.filter((name) => files.includes(name)).concat(files.filter((name) => !current.includes(name)));
  ElainaData.set(dataKey, next);
  if (dataKey === "Wallpaper-list" && ElainaData.get("wallpaper-index") >= next.length)
    ElainaData.set("wallpaper-index", 0);
  if (dataKey === "Audio-list" && ElainaData.get("audio-index") >= next.length)
    ElainaData.set("audio-index", 0);
  return next;
}
async function createFileListRow(type, dataKey, inputKey, regex) {
  // The theme needs at least one wallpaper and one audio file
  const keepOne = type === "wallpaper" || type === "audio";
  const row = document.createElement("div");
  row.className = "parasite-asset-row";
  const head = document.createElement("div");
  head.className = "parasite-asset-head";
  const title = document.createElement("span");
  title.textContent = await getString(assetLocaleKeys[type]);
  const add = document.createElement("lol-uikit-flat-button");
  add.textContent = parasiteTr("Add");
  add.addEventListener("click", () => parasiteAssets(type, "open"));
  head.append(title, add);
  const list = document.createElement("div");
  list.className = "parasite-asset-list";
  const hint = document.createElement("div");
  hint.className = "parasite-asset-hint";
  row.append(head, list, hint);
  const idleHint = parasiteTr("Drop files here, or Add to open the folder");
  let names = ElainaData.get(dataKey) || [];
  const show = (files, error) => {
    if (Array.isArray(files))
      names = syncParasiteAssetList(dataKey, files);
    list.replaceChildren(...names.map((name) => {
      const chip = document.createElement("span");
      chip.className = "parasite-asset-chip";
      chip.textContent = name;
      const remove = document.createElement("span");
      remove.className = "parasite-asset-remove";
      remove.textContent = "\\u00d7";
      remove.title = parasiteTr("Delete");
      remove.addEventListener("click", async () => {
        if (keepOne && names.length <= 1) {
          hint.textContent = parasiteTr("Keep at least one");
          return;
        }
        const reply = await parasiteAssets(type, "delete", { name });
        show(reply.files, reply.error);
      });
      chip.appendChild(remove);
      return chip;
    }));
    hint.textContent = error || idleHint;
    hint.classList.toggle("error", !!error);
  };
  show(null, "");
  row.addEventListener("dragover", (event) => {
    event.preventDefault();
    row.classList.add("dragging");
  });
  row.addEventListener("dragleave", () => row.classList.remove("dragging"));
  row.addEventListener("drop", async (event) => {
    event.preventDefault();
    row.classList.remove("dragging");
    for (const file of Array.from(event.dataTransfer.files || [])) {
      if (!regex.test(file.name.toLowerCase())) {
        show(null, parasiteTr("{name} isn't a {type} file", { name: file.name, type: title.textContent.toLowerCase() }));
        continue;
      }
      hint.textContent = parasiteAddingText(file);
      const reply = await uploadParasiteAsset(type, file, (done) => { hint.textContent = parasiteAddingText(file, done); });
      show(reply.files, reply.error);
    }
  });
  // Files pasted into the folder show up when the player comes back to the client
  const refresh = async () => {
    if (!document.body.contains(row)) {
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      return;
    }
    const reply = await parasiteAssets(type, "list");
    if (Array.isArray(reply.files)) show(reply.files, reply.error);
  };
  const timer = setInterval(refresh, 4000);
  window.addEventListener("focus", refresh);
  setTimeout(refresh, 0);
  return [row];
}
async function assetLibrarySection() {
  return UI.createSection("theme-settings-asset-library", await getString("theme-settings.settings-section-asset-library"), [
    ...await createFileListRow("wallpaper", "Wallpaper-list", "manual-wallpaper-name", fileRegex.Wallpaper),
    ...await createFileListRow("audio", "Audio-list", "manual-audio-name", fileRegex.Audio),
    ...await createFileListRow("banner", "Banner-list", "manual-banner-name", fileRegex.Banner),
    ...await createFileListRow("font", "Font-list", "manual-font-name", fileRegex.Font)
  ]);
}

'''


# (file, start, end[, replacement]): text from start up to end, cut or replaced,
# for blocks too long to quote.
CUTS = [
    ("index.js",
     "async function createFileListRow(type, dataKey, inputKey, regex) {\n",
     "const windowEffectList = {\n",
     ASSET_LIBRARY_JS),
    # Fake mastery score and rank sent to friends: removed with their settings.
    ("index.js",
     '      UI.createCheckBox(\n        `${await getString("plugins-settings.custom-mastery-score")}`,',
     '      UI.createCheckBox(\n        `${await getString("plugins-settings.custom-challenge-crystal")}`,'),
    # The theme's own nickname color settings (replaced by the CUSTOMIZE tab).
    ("index.js",
     '    UI.createCheckBox(\n      `${await getString("theme-settings.change-nickname-color")}`,',
     '    UI.createCheckBox(\n      `${await getString("theme-settings.hide-theme-usage-time")}`,'),
]


def apply_patches(root):
    for rel, start, end, *replacement in CUTS:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        a = text.find(start)
        b = text.find(end, a + 1) if a >= 0 else -1
        if a < 0 or b < 0 or text.count(start) != 1:
            sys.exit(f"[theme] cut not found in {rel}: {start[:70]!r}")
        path.write_text(text[:a] + "".join(replacement) + text[b:], encoding="utf-8")

    for rel, old, new in PATCHES:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if old not in text:
            sys.exit(f"[theme] patch target not found in {rel}: {old[:70]!r}")
        path.write_text(text.replace(old, new), encoding="utf-8")

    index = root / "index.js"
    text = index.read_text(encoding="utf-8")
    start = text.find("async function aboutustab(panel) {")
    end = text.find("const datapath$5 = ", start)
    if start < 0 or end < 0:
        sys.exit("[theme] about-us tab not found in index.js")
    index.write_text(text[:start] + ABOUT_US + text[end:], encoding="utf-8")


def rename_tree(root):
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            # The MIT notice keeps Elaina's copyright line as the license requires.
            renamed = text if path.name == "LICENSE.txt" else rename(text)
            # Every text file with LF endings: the release mixes in CRLF, and the
            # output must be the same whichever OS builds it.
            path.write_text(renamed, encoding="utf-8", newline="\n")
        if "elaina" in path.name.lower():
            path.rename(path.with_name(rename(path.name)))


# Elaina's pinks, swapped for League's light gold or Parasite's purple everywhere they appear.
COLOR_SWAPS = [
    ("#fff1f1", "#f0e6d2"),                                   # nav icons and labels
    ("rgb(255 236 236)", "rgb(240 230 210)"),                 # level XP ring
    ("rgb(90 27 62 / 20%)", "rgb(59 29 110 / 20%)"),          # lobby background tint
    ("rgba(248, 169, 201, 0.726)", "rgba(139, 92, 246, 0.726)"),  # ticker
    ("6px pink)", "6px #8b5cf6)"),                            # glow on wallpaper and audio controls
    ("3px pink)", "3px #8b5cf6)"),
    ("#f77fbe", "#8b5cf6"),                                   # console tag
]


def recolor(root):
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".css", ".js"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        swapped = text
        for old, new in COLOR_SWAPS:
            swapped = swapped.replace(old, new)
        if swapped != text:
            path.write_text(swapped, encoding="utf-8", newline="\n")
    left = [old for old, _ in COLOR_SWAPS
            if any(old in p.read_text(encoding="utf-8") for p in root.rglob("*.css"))]
    if left:
        sys.exit(f"[theme] colors left: {left}")


# Artwork ---------------------------------------------------------------------

VOID_TOP = (18, 10, 36)
VOID_BOTTOM = (59, 29, 110)


def gradient(size, top=VOID_TOP, bottom=VOID_BOTTOM):
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def fit(img, size):
    img = img.copy()
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return canvas


def with_logo(bg, logo, width_ratio, opacity=1.0, glow=True):
    bg = bg.convert("RGBA")
    logo = logo.copy()
    target = int(bg.width * width_ratio)
    logo = logo.resize((target, int(logo.height * target / logo.width)), Image.LANCZOS)
    if opacity < 1:
        logo.putalpha(logo.getchannel("A").point(lambda a: int(a * opacity)))
    pos = ((bg.width - logo.width) // 2, (bg.height - logo.height) // 2)
    if glow:
        halo = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        shadow = Image.new("RGBA", logo.size, (139, 92, 246, 0))
        shadow.putalpha(logo.getchannel("A").point(lambda a: int(a * 0.8)))
        halo.alpha_composite(shadow, pos)
        bg.alpha_composite(halo.filter(ImageFilter.GaussianBlur(bg.width // 60)))
    bg.alpha_composite(logo, pos)
    return bg


def write_silence(path, seconds=1, rate=8000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(rate)
        wav.writeframes(bytes([128]) * rate * seconds)


def make_art(root):
    word = Image.open(BRAND / "golden_parasite.png").convert("RGBA")
    word = word.crop(word.getbbox())
    ring = Image.open(BRAND / "parasite_without_bg.png").convert("RGBA")
    square = Image.open(BRAND / "icon.png").convert("RGBA")
    icon = root / "assets" / "icon"
    bgs = root / "assets" / "backgrounds"

    for name in ("parasite-wallpaper.webm", "parasite-dark.jpg"):
        shutil.copy2(HERE / "art" / name, bgs / "wallpapers" / name)
    with_logo(gradient((1920, 1080)), word, 0.32).convert("RGB").save(
        bgs / "wallpapers" / "parasite-wallpaper.jpg", quality=90)
    write_silence(bgs / "audio" / "parasite-silence.wav")

    fit(word, (551, 476)).save(icon / "animation-logo.png")
    fit(ring, (250, 250)).save(icon / "logo.png")
    fit(ring, (320, 320)).save(icon / "loading.png")
    square.resize((362, 362), Image.LANCZOS).save(icon / "avatar.png")
    for name, size in [("clash.png", 300), ("rank.png", 300), ("rp-icon.png", 128),
                       ("be-icon.png", 128), ("ticker.png", 128), ("mouse-cursor.png", 32)]:
        fit(ring, (size, size)).save(icon / name)

    with_logo(gradient((1600, 900)), word, 0.25, opacity=0.35, glow=False).convert("RGB").save(
        icon / "hover-card-backdrop.jpg", quality=90)
    with_logo(gradient((1280, 720)), word, 0.3, opacity=0.5).convert("RGB").save(
        icon / "plugins-icons" / "ll-settings.jpg", quality=90)

    # One tint per rune tree, used only when "Runes-BG" is turned on.
    tints = {"precision": (200, 170, 110), "domination": (210, 60, 70), "sorcery": (110, 120, 240),
             "resolve": (90, 190, 120), "inspiration": (80, 200, 220)}
    for name, tint in tints.items():
        bottom = tuple((a + b) // 2 for a, b in zip(VOID_BOTTOM, tint))
        with_logo(gradient((1920, 1080), VOID_TOP, bottom), word, 0.2, opacity=0.25, glow=False) \
            .convert("RGB").save(bgs / "runes" / f"{name}.jpg", quality=88)


# Data module -------------------------------------------------------------------

def install_data(root, data_pkg, version):
    data = root / f"elaina-theme-data@{version}"
    shutil.copytree(HERE / "data", data)
    (data / "src" / "update").mkdir(parents=True, exist_ok=True)
    shutil.copy2(data_pkg / "src" / "update" / "update.js", data / "src" / "update" / "update.js")
    shutil.copy2(data_pkg / "LICENSE.txt", data / "LICENSE.txt")

    (root / "config" / "cdnServer.js").write_text(
        "// Parasite: the theme data module ships inside this plugin instead of loading from a CDN.\n"
        "export default {\n"
        '    "cdn-url": new URL("../", import.meta.url).href,\n'
        f'    "version": "{version}"\n'
        "}\n",
        encoding="utf-8",
    )


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    release_zip, data_tgz = map(Path, sys.argv[1:])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        theme = tmp / "theme"
        with zipfile.ZipFile(release_zip) as z:
            z.extractall(theme)
        with tarfile.open(data_tgz) as t:
            t.extractall(tmp / "data", filter="data")
        data_pkg = tmp / "data" / "package"
        version = re.search(r'"version":\s*"([^"]+)"',
                            (data_pkg / "package.json").read_text(encoding="utf-8")).group(1)

        for rel in REMOVE:
            path = theme / rel
            if not path.exists():
                sys.exit(f"[theme] expected file missing from release: {rel}")
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        (theme / "config" / "champsBgList.js").write_text("export default []\n", encoding="utf-8")

        apply_patches(theme)
        make_art(theme)
        install_data(theme, data_pkg, version)
        for locale in (HERE / "locales").glob("*.js"):
            shutil.copy2(locale, theme / "locales" / locale.name)
        shutil.copy2(data_pkg / "LICENSE.txt", theme / "LICENSE.txt")
        rename_tree(theme)
        recolor(theme)

        leftovers = [str(p.relative_to(theme)) for p in theme.rglob("*")
                     if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and p.name != "LICENSE.txt"
                     and re.search(r"elaina", p.read_text(encoding="utf-8"), re.I)]
        if leftovers:
            sys.exit(f"[theme] Elaina left in: {leftovers}")

        if OUT.exists():
            shutil.rmtree(OUT)
        shutil.copytree(theme, OUT)
    print(f"[theme] PARASITE-Theme {version} written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
