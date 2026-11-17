"""Parasite speaks Turkish only: the Turkish texts parasite/sync.py puts in Rose's files.

Everything a player sees (dialogs, tray menu, installer, Pengu Loader's window, client plugins)
is in Turkish, with no English to choose. Log messages, code and developer-only text stay English.

- TURKISH: (file, English, Turkish). Every occurrence of the English text in the file is
  replaced, and it must occur at least once (sync fails loudly when Rose changed it).
- LOCALE_TR: client plugin texts (PARASITE-I18n keys) Rose's tr.json has no Turkish for.
- TR_JSON_FIXES: corrections to Rose's tr.json, applied to its Turkish values.
"""

LOG_FOLDER = "Kayıt klasörünü aç"  # the tray menu item, named in dialogs and plugin texts
DIAGNOSE = "Başlangıç sorununu tanıla"  # the tray menu item that collects report.txt / report.json
ISSUES_URL = "https://github.com/lustmyself/Parasite/issues"


def ps_text(text):
    """A PowerShell 5.1 expression for *text*: apply.ps1 is written as UTF-8 without a BOM, which
    Windows PowerShell reads in the ANSI code page, so letters outside ASCII go as \\u escapes."""
    escaped = "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in text).replace("'", "''")
    return f"[regex]::Unescape('{escaped}')"


TURKISH = [
    # ---- main/__init__.py: startup dialogs ----
    ("main/__init__.py", '"Parasite - LTK Manager Missing"', '"Parasite - LTK Manager bulunamadı"'),
    ("main/__init__.py", '"Parasite couldn\'t install LTK Manager",',
     '"Parasite, LTK Manager\'ı kuramadı",'),
    ("main/__init__.py",
     '            "Parasite applies skins through LTK Manager and tried to install it for you, but the "\n'
     '            "download or the installation did not finish (no internet, or the Windows prompt was "\n'
     '            "declined). It only has to be installed once: Parasite "\n'
     '            "opens it in the background during champ select and closes it after the game, "\n'
     '            "so you never have to open it yourself.",\n'
     '            "1. Restart Parasite to try again, and click Yes on the Windows prompt. Or install "\n'
     '            f"LTK Manager yourself ({LTK_MANAGER_DOWNLOAD_URL}).\\n"\n'
     '            "2. Already installed in another folder? Click Set up path and select its "\n'
     '            "ltk-manager.exe: Parasite remembers it and starts right away.",\n'
     '            "Set up path",\n',
     '            "Parasite skinleri LTK Manager üzerinden uygular ve onu senin için kurmayı denedi, ama "\n'
     '            "indirme ya da kurulum bitmedi (internet yok ya da Windows\'un sorusu reddedildi). "\n'
     '            "Yalnızca bir kez kurulması yeter: Parasite onu şampiyon seçiminde arka planda açar "\n'
     '            "ve maçtan sonra kapatır, senin hiç açman gerekmez.",\n'
     '            "1. Tekrar denemek için Parasite\'ı yeniden başlat ve Windows\'un sorusunda Evet\'e tıkla. "\n'
     '            f"Ya da LTK Manager\'ı kendin kur ({LTK_MANAGER_DOWNLOAD_URL}).\\n"\n'
     '            "2. Başka bir klasöre mi kurulu? Yolu ayarla\'ya tıkla ve oradaki ltk-manager.exe\'yi seç: "\n'
     '            "Parasite onu hatırlar ve hemen açılır.",\n'
     '            "Yolu ayarla",\n'),
    ("main/__init__.py",
     '        "Parasite - Missing Component",\n'
     '        "One Parasite component is missing",\n'
     '        f"Parasite needs {detail or \'its bridge files\'} in its tools folder before it can start.",\n'
     '        "1. Reinstall Parasite: these files are part of every install.\\n"\n'
     '        "2. If an antivirus removed them, restore the files or add Parasite\'s folder to its exclusions.\\n"\n'
     '        "3. Restart Parasite.",\n'
     '        "Open tools folder",\n',
     '        "Parasite - Eksik bileşen",\n'
     '        "Parasite\'ın bir bileşeni eksik",\n'
     '        f"Parasite\'ın açılabilmesi için araçlar klasöründe {detail or \'köprü dosyaları\'} gerekiyor.",\n'
     '        "1. Parasite\'ı yeniden kur: bu dosyalar her kurulumda gelir.\\n"\n'
     '        "2. Bir antivirüs onları sildiyse dosyaları geri yükle ya da Parasite\'ın klasörünü antivirüsün istisnalarına ekle.\\n"\n'
     '        "3. Parasite\'ı yeniden başlat.",\n'
     '        "Araçlar klasörünü aç",\n'),
    ("main/__init__.py", 'TaskDialogButton(button_close, "Close Parasite")',
     'TaskDialogButton(button_close, "Parasite\'ı kapat")'),
    ("main/__init__.py", '\\n\\nHow to fix it:\\n{steps}', '\\n\\nNasıl düzeltilir:\\n{steps}'),
    ("main/__init__.py", f'"Need help? Open an issue: {ISSUES_URL}', f'"Yardım mı lazım? Sorun bildir: {ISSUES_URL}'),
    ("main/__init__.py", 'f"Press OK to {action.lower()}, or Cancel to close Parasite."',
     'f"Tamam: {action}. İptal: Parasite\'ı kapat."'),
    ("main/__init__.py", 'lpstrTitle="Select LTK Manager (ltk-manager.exe)",',
     'lpstrTitle="LTK Manager\'ı seç (ltk-manager.exe)",'),
    ("main/__init__.py", '\\0Programs (*.exe)\\0', '\\0Programlar (*.exe)\\0'),
    ("main/__init__.py",
     '            f"{picked.name} is not LTK Manager.\\n\\nSelect ltk-manager.exe in the folder LTK Manager "\n'
     '            "is installed in.",\n',
     '            f"{picked.name}, LTK Manager değil.\\n\\nLTK Manager\'ın kurulu olduğu klasördeki "\n'
     '            "ltk-manager.exe\'yi seç.",\n'),
    ("main/__init__.py",
     '            "Parasite could not save the path in its cf.ini.\\n\\nCheck that Parasite can write to "\n'
     '            "%LOCALAPPDATA%\\\\Parasite, then try again.",\n',
     '            "Parasite yolu cf.ini dosyasına kaydedemedi.\\n\\nParasite\'ın %LOCALAPPDATA%\\\\Parasite "\n'
     '            "klasörüne yazabildiğini kontrol et, sonra tekrar dene.",\n'),
    ("main/__init__.py",
     '                "Parasite could not activate Pengu Loader, so it will not appear in the League client.\\n\\n"\n'
     '                "Close the League client, then restart Parasite.\\n"\n'
     '                "If it happens again, make sure your antivirus is not blocking Pengu Loader.\\n\\n"\n'
     '                "Details are in %LOCALAPPDATA%\\\\Parasite\\\\logs\\\\",\n',
     '                "Parasite, Pengu Loader\'ı etkinleştiremedi; bu yüzden League istemcisinde görünmeyecek.\\n\\n"\n'
     '                "League istemcisini kapat, sonra Parasite\'ı yeniden başlat.\\n"\n'
     '                "Yine olursa antivirüsünün Pengu Loader\'ı engellemediğinden emin ol.\\n\\n"\n'
     '                "Ayrıntılar %LOCALAPPDATA%\\\\Parasite\\\\logs\\\\ klasöründe.",\n'),
    ("main/__init__.py",
     '            "Parasite did not load into this League client: Pengu Loader\'s DLL is missing from it.\\n\\n"\n'
     '            "Right-click Parasite\'s system tray icon and choose Diagnose Parasite startup. "\n'
     '            "Keep League open while collecting the report.\\n\\n"\n'
     f'            "Then attach report.txt and report.json to a GitHub issue ({ISSUES_URL}), so we can find out why. "\n'
     '            "You can also paste them into an AI assistant for a first look.",\n'
     '            "Parasite - Client injection failed",\n',
     '            "Parasite bu League istemcisine yüklenmedi: Pengu Loader\'ın DLL\'i istemcide yok.\\n\\n"\n'
     f'            "Sistem tepsisindeki Parasite simgesine sağ tıkla ve {DIAGNOSE}\'yı seç. "\n'
     '            "Rapor toplanırken League açık kalsın.\\n\\n"\n'
     f'            "Sonra nedenini bulabilmemiz için report.txt ve report.json dosyalarını bir GitHub sorun bildirimine ekle ({ISSUES_URL}). "\n'
     '            "İlk bakış için onları bir yapay zekâ asistanına da yapıştırabilirsin.",\n'
     '            "Parasite - İstemciye yüklenemedi",\n'),
    ("main/__init__.py",
     '                    f"Parasite crashed with an unhandled error:\\n\\n{str(e)}\\n\\nError type: {type(e).__name__}'
     '\\n\\nPlease check the log file in:\\n%LOCALAPPDATA%\\\\Parasite\\\\logs\\\\",\n'
     '                    "Parasite - Fatal Error",\n',
     '                    f"Parasite beklenmeyen bir hatayla kapandı:\\n\\n{str(e)}\\n\\nHata türü: {type(e).__name__}'
     '\\n\\nKayıt dosyasına bak:\\n%LOCALAPPDATA%\\\\Parasite\\\\logs\\\\",\n'
     '                    "Parasite - Ölümcül hata",\n'),

    # ---- main/core: one instance, initialization errors ----
    ("main/core/lockfile.py",
     '"Another instance of Parasite is already running!\\n\\nPlease close the existing instance before starting a new one."',
     '"Parasite zaten çalışıyor!\\n\\nYenisini açmadan önce çalışan Parasite\'ı kapat."'),
    ("main/core/lockfile.py", '"Parasite - Instance Already Running"', '"Parasite - Zaten çalışıyor"'),
    ("main/core/initialization.py",
     'f"Parasite failed to initialize:\\n\\n{str(e)}\\n\\nCheck the log file for details:\\n{get_log_file() or \'N/A\'}"',
     'f"Parasite başlatılamadı:\\n\\n{str(e)}\\n\\nAyrıntılar kayıt dosyasında:\\n{get_log_file() or \'yok\'}"'),
    ("main/core/initialization.py", '"Parasite - Initialization Error"', '"Parasite - Başlatma hatası"'),
    ("main/core/initialization.py",
     'f"Parasite failed to initialize injection system:\\n\\n{str(e)}\\n\\nCheck the log file for details:\\n{get_log_file() or \'N/A\'}"',
     'f"Parasite\'ın skin yükleme sistemi başlatılamadı:\\n\\n{str(e)}\\n\\nAyrıntılar kayıt dosyasında:\\n{get_log_file() or \'yok\'}"'),
    ("main/core/initialization.py", '"Parasite - Injection Error"', '"Parasite - Skin yükleme hatası"'),
    ("main/setup/initialization.py", 'f"Parasite - preparing mods ({index}/{total}): {name}"',
     'f"Parasite - modlar hazırlanıyor ({index}/{total}): {name}"'),

    # ---- utils/system/admin_utils.py ----
    ("utils/system/admin_utils.py",
     '        "Parasite requires Administrator privileges to function properly.\\n\\n"\n'
     '        "The application will now request elevation.\\n\\n"\n'
     '        "Click \'Yes\' on the UAC prompt to continue.",\n'
     '        "Administrator Rights Required",\n',
     '        "Parasite\'ın düzgün çalışması için yönetici izni gerekiyor.\\n\\n"\n'
     '        "Şimdi yönetici izni istenecek.\\n\\n"\n'
     '        "Devam etmek için Windows\'un sorusunda \'Evet\'e tıkla.",\n'
     '        "Yönetici izni gerekiyor",\n'),
    ("utils/system/admin_utils.py",
     '        "Parasite will now start automatically when turn on your computer.",\n'
     '        "Auto-Start Enabled",\n',
     '        "Parasite artık bilgisayarını açınca kendiliğinden başlayacak.",\n'
     '        "Windows ile başlatma açık",\n'),
    ("utils/system/admin_utils.py",
     '        "Parasite has been removed from auto-start.\\n\\n"\n'
     '        "The application will no longer start automatically with Windows.\\n\\n"\n'
     '        "You can re-enable auto-start from the settings menu.",\n'
     '        "Auto-Start Removed",\n',
     '        "Parasite artık Windows ile başlamayacak.\\n\\n"\n'
     '        "Bunu ayarlardan yeniden açabilirsin.",\n'
     '        "Windows ile başlatma kapalı",\n'),

    # ---- the tray icon's menu and notifications ----
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Parasite Hub", ', 'pystray.MenuItem("Parasite\'ı aç", '),
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Open Mods Folder", ', 'pystray.MenuItem("Mod klasörünü aç", '),
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Status", ', 'pystray.MenuItem("Durum", '),
    ("utils/integration/tray_manager.py",
     '"Diagnosing Parasite startup..." if self._diagnostics_lock.locked() else "Diagnose Parasite startup"',
     f'"Başlangıç tanılanıyor..." if self._diagnostics_lock.locked() else "{DIAGNOSE}"'),
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Open Logs folder", ', f'pystray.MenuItem("{LOG_FOLDER}", '),
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Restart", ', 'pystray.MenuItem("Yeniden başlat", '),
    ("utils/integration/tray_manager.py", 'pystray.MenuItem("Quit", ', 'pystray.MenuItem("Kapat", '),
    ("utils/integration/tray_manager.py", 'self.icon.notify(message, "Parasite startup diagnostics")',
     'self.icon.notify(message, "Parasite başlangıç tanılaması")'),
    ("utils/integration/tray_manager.py", '"Could not start diagnostics. Please retry."',
     '"Tanılama başlatılamadı. Tekrar dene."'),
    ("utils/integration/tray_manager.py",
     '"Diagnostics started. Checking Windows and Parasite; this can take up to 3 minutes."',
     '"Tanılama başladı. Windows ve Parasite kontrol ediliyor; bu 3 dakika kadar sürebilir."'),
    ("utils/integration/tray_manager.py", '"Reports saved. Use Open Logs folder in the tray menu."',
     f'"Raporlar kaydedildi. Tepsi menüsünden {LOG_FOLDER}\'ı kullan."'),
    ("utils/integration/tray_manager.py",
     '"Could not save diagnostics. Check the Parasite logs and folder permissions."',
     '"Tanılama kaydedilemedi. Parasite kayıtlarını ve klasör izinlerini kontrol et."'),
    ("utils/integration/tray_manager.py", '"Could not open the logs folder. Check folder permissions."',
     '"Kayıt klasörü açılamadı. Klasör izinlerini kontrol et."'),
    ("utils/integration/tray_manager.py", 'f"Failed to open settings dialog:\\n\\n{e}",\n                    "Parasite Settings",',
     'f"Ayarlar penceresi açılamadı:\\n\\n{e}",\n                    "Parasite ayarları",'),

    # ---- the startup diagnostics window and its verdicts ----
    ("utils/integration/diagnostics_progress.py", 'window_title="Diagnose Parasite startup"',
     f'window_title="{DIAGNOSE}"'),
    ("utils/integration/diagnostics_progress.py", '"STATIC", "Diagnostics started", ', '"STATIC", "Tanılama başladı", '),
    ("utils/integration/diagnostics_progress.py",
     '"Checking Windows and Parasite. Keep the League client open.\\nThis can take up to 3 minutes."',
     '"Windows ve Parasite kontrol ediliyor. League istemcisi açık kalsın.\\nBu 3 dakika kadar sürebilir."'),
    ("utils/integration/diagnostics_progress.py", '"STATIC", "Collecting... 0 seconds", ',
     '"STATIC", "Toplanıyor... 0 saniye", '),
    ("utils/integration/diagnostics_progress.py", 'f"Collecting... {int(time.monotonic() - self.started)} seconds"',
     'f"Toplanıyor... {int(time.monotonic() - self.started)} saniye"'),
    ("utils/integration/diagnostics_progress.py", '"BUTTON", "Open reports", ', '"BUTTON", "Raporları aç", '),
    ("utils/integration/diagnostics_progress.py", '"BUTTON", "Run in background", ',
     '"BUTTON", "Arka planda çalıştır", '),
    ("utils/integration/diagnostics_progress.py",
     '"Diagnostics complete" if succeeded else "Diagnostics could not finish"',
     '"Tanılama tamamlandı" if succeeded else "Tanılama bitirilemedi"'),
    ("utils/integration/diagnostics_progress.py",
     '"Reports saved." if directory else "Check the Parasite logs for details."',
     '"Raporlar kaydedildi." if directory else "Ayrıntılar için Parasite kayıtlarına bak."'),
    ("utils/integration/diagnostics_progress.py", 'self.set_label_text(self.close_button, "Close")',
     'self.set_label_text(self.close_button, "Kapat")'),
    ("utils/integration/diagnostics_progress.py", '"Could not open reports. Use Open Logs folder in the tray."',
     f'"Raporlar açılamadı. Tepsideki {LOG_FOLDER}\'ı kullan."'),
    ("utils/core/startup_diagnostics.py",
     '"Collecting. If Parasite exits unexpectedly, this run may be incomplete."',
     '"Toplanıyor. Parasite beklenmedik şekilde kapanırsa bu rapor eksik kalabilir."'),
    ("utils/core/startup_diagnostics.py", '"Collection cancelled because Parasite is stopping."',
     '"Parasite kapandığı için toplama iptal edildi."'),
    ("utils/core/startup_diagnostics.py",
     '"The bundled diagnostic script is missing. Repair or reinstall Parasite."',
     '"Tanılama betiği eksik. Parasite\'ı onar ya da yeniden kur."'),
    ("utils/core/startup_diagnostics.py",
     '"Windows PowerShell 5.1 could not be found. Check your Windows installation."',
     '"Windows PowerShell 5.1 bulunamadı. Windows kurulumunu kontrol et."'),
    ("utils/core/startup_diagnostics.py",
     '"Collection timed out after 3 minutes. A Windows query may be unresponsive. "\n'
     '                            "Any existing reports are incomplete; retry and share this status with support."',
     '"Toplama 3 dakikada bitmedi: bir Windows sorgusu yanıt vermiyor olabilir. "\n'
     '                            "Oluşan raporlar eksik; tekrar dene ve bu durumu destekle paylaş."'),
    ("utils/core/startup_diagnostics.py",
     'f"The diagnostic collector exited with code {process.returncode}. "\n'
     '                    "Any existing reports are incomplete. Check Windows PowerShell availability "\n'
     '                    "and application-control history with support; a collector failure does not "\n'
     '                    "establish why Parasite failed to start."',
     'f"Tanılama aracı {process.returncode} koduyla kapandı. "\n'
     '                    "Oluşan raporlar eksik. Windows PowerShell\'in çalışıp çalışmadığını ve uygulama "\n'
     '                    "denetimi geçmişini destekle birlikte kontrol et; aracın hatası Parasite\'ın neden "\n'
     '                    "açılmadığını göstermez."'),
    ("utils/core/startup_diagnostics.py",
     'f"Windows could not run the diagnostic collector (error {getattr(error, \'winerror\', None) or error.errno}). "\n'
     '            "Check Windows PowerShell and application-control history with support."',
     'f"Windows tanılama aracını çalıştıramadı (hata {getattr(error, \'winerror\', None) or error.errno}). "\n'
     '            "Windows PowerShell\'i ve uygulama denetimi geçmişini destekle birlikte kontrol et."'),
    ("utils/core/startup_diagnostics.py",
     '"The collector did not produce complete reports. Retry and share this status with support."',
     '"Tanılama aracı raporları tamamlayamadı. Tekrar dene ve bu durumu destekle paylaş."'),
    ("utils/core/startup_diagnostics.py",
     'f"Collection complete: {counts[\'FAIL\']} FAIL, {counts[\'WARN\']} WARN, "\n'
     '        f"{counts[\'UNKNOWN\']} UNKNOWN. Read report.txt for evidence and next steps."',
     'f"Toplama tamamlandı: {counts[\'FAIL\']} HATA, {counts[\'WARN\']} UYARI, "\n'
     '        f"{counts[\'UNKNOWN\']} BİLİNMİYOR. Kanıtlar ve sonraki adımlar report.txt dosyasında."'),

    # ---- the launcher (updates before Parasite starts) ----
    ("launcher/core/launcher.py", '"Parasite - Launcher",', '"Parasite - Başlatıcı",'),
    ("launcher/core/launcher.py", 'dialog.set_status(f"Parasite {remote_version} is ready to install.")',
     'dialog.set_status(f"Parasite {remote_version} kurulmaya hazır.")'),
    ("launcher/core/launcher.py",
     '        f"A new version of Parasite is available.\\n\\n"\n'
     '        f"Current version: {local_version}\\n"\n'
     '        f"New version: {remote_version}\\n\\n"\n'
     '        "Do you want to download and install it now?"\n',
     '        f"Parasite\'ın yeni bir sürümü var.\\n\\n"\n'
     '        f"Şu anki sürüm: {local_version}\\n"\n'
     '        f"Yeni sürüm: {remote_version}\\n\\n"\n'
     '        "Şimdi indirip kurmak ister misin?"\n'),
    ("launcher/core/launcher.py", '"Parasite update available",', '"Parasite güncellemesi var",'),
    ("launcher/core/launcher.py", '_show_error(f"Failed to prepare Parasite:\\n\\n{exc}")',
     '_show_error(f"Parasite hazırlanamadı:\\n\\n{exc}")'),
    ("launcher/ui/update_dialog.py", '"Preparing Parasite…"', '"Parasite hazırlanıyor…"'),
    # The launcher's own window (when the hub can't show) words its steps as the hub does
    ("launcher/ui/update_dialog.py", 'updater_log = get_named_logger("updater", prefix="log_updater")\n',
     'updater_log = get_named_logger("updater", prefix="log_updater")\n\n\n'
     'def _turkish(text: str) -> str:\n'
     '    """Parasite is Turkish only: the launcher\'s steps as the desktop hub words them."""\n'
     '    try:\n'
     '        from launcher.parasite_hub import _translate\n'
     '        return _translate(text)\n'
     '    except Exception:  # noqa: BLE001 - the English text is better than no text\n'
     '        return text\n'),
    ("launcher/ui/update_dialog.py",
     '    def set_detail(self, text: str) -> None:\n        updater_log.info(f"Detail: {text}")\n',
     '    def set_detail(self, text: str) -> None:\n        updater_log.info(f"Detail: {text}")\n'
     '        text = _turkish(text)\n'),
    ("launcher/ui/update_dialog.py",
     '    def set_status(self, text: str) -> None:\n        updater_log.info(f"Status: {text}")\n',
     '    def set_status(self, text: str) -> None:\n        updater_log.info(f"Status: {text}")\n'
     '        text = _turkish(text)\n'),
    ("launcher/update/update_installer.py",
     '        "Parasite could not complete the update. The log is at " + $log +\n'
     '        ". If Parasite cannot start, run Recover-Parasite.cmd as administrator from " + $PSScriptRoot + ".",\n'
     "        'Parasite update failed', 'OK', 'Error')\n",
     f"        ({ps_text('Parasite güncellemeyi tamamlayamadı. Kayıt dosyası: ')} + $log +\n"
     f"        {ps_text('. Parasite açılmazsa ')} + $PSScriptRoot +\n"
     f"        {ps_text(' klasöründeki Recover-Parasite.cmd dosyasını yönetici olarak çalıştır.')}),\n"
     f"        {ps_text('Parasite güncellemesi başarısız')}, 'OK', 'Error')\n"),

    # ---- moving the mods into LTK Manager's library (once, from older versions) ----
    ("launcher/sequences/mod_migration_sequence.py", 'TITLE = "Parasite - your mods"', 'TITLE = "Parasite - modların"'),
    ("launcher/sequences/mod_migration_sequence.py",
     '    "Parasite now keeps the mods you added in LTK Manager\'s library, without a copy of its own, "\n'
     '    "and moves your mods there now.\\n\\n"\n'
     '    "Do you want a backup of your mods on your desktop first? ({size}, {free} free)\\n\\n"\n'
     '    "Yes: copy them to a \\"Parasite mods backup\\" folder on your desktop, then move them.\\n"\n'
     '    "No: move them without a backup."\n',
     '    "Parasite artık eklediğin modları kendi kopyası olmadan LTK Manager\'ın kütüphanesinde tutuyor "\n'
     '    "ve modlarını şimdi oraya taşıyor.\\n\\n"\n'
     '    "Önce masaüstüne modlarının bir yedeğini almak ister misin? ({size}, boş alan {free})\\n\\n"\n'
     '    "Evet: masaüstündeki \\"Parasite mod yedeği\\" klasörüne kopyala, sonra taşı.\\n"\n'
     '    "Hayır: yedeklemeden taşı."\n'),
    ("launcher/sequences/mod_migration_sequence.py", '"Packing your mods ({index}/{total}): {name}"',
     '"Modların paketleniyor ({index}/{total}): {name}"'),
    ("launcher/sequences/mod_migration_sequence.py", '"Opening LTK Manager to move your mods…"',
     '"Modlarını taşımak için LTK Manager açılıyor…"'),
    ("launcher/sequences/mod_migration_sequence.py", '"Backing up your mods to your desktop…"',
     '"Modların masaüstüne yedekleniyor…"'),
    ("launcher/sequences/mod_migration_sequence.py", '"Moving your mods into LTK Manager ({index}/{total}): {name}"',
     '"Modların LTK Manager\'a taşınıyor ({index}/{total}): {name}"'),
    ("launcher/sequences/mod_migration_sequence.py", 'self._detail = "Back up your mods?"',
     'self._detail = "Modların yedeklensin mi?"'),
    ("injection/mods/migration.py", 'BACKUP_FOLDER = "Parasite mods backup {date:%Y-%m-%d}"',
     'BACKUP_FOLDER = "Parasite mod yedeği {date:%Y-%m-%d}"'),
    ("injection/mods/migration.py",
     '                f"Your mods need {size_text(need)} free on the drive of LTK Manager\'s library ({_existing(root)}), "\n'
     '                f"and {size_text(free)} is free there.\\n\\nFree some space: your mods stay in Parasite and work as "\n'
     '                "before until then, and Parasite moves them the next time it starts.",\n',
     '                f"Modların için LTK Manager kütüphanesinin sürücüsünde ({_existing(root)}) {size_text(need)} "\n'
     '                f"boş alan gerekiyor, orada {size_text(free)} boş.\\n\\nBiraz yer aç: o zamana kadar modların "\n'
     '                "Parasite\'ta kalır ve eskisi gibi çalışır, Parasite onları bir sonraki açılışta taşır.",\n'),
    ("injection/mods/migration.py",
     '    return (f"Parasite could not move your mods into LTK Manager: {reason}.\\n\\n"\n'
     '            "Your mods stay in Parasite and work as before. Parasite tries again the next time it starts "\n'
     '            "(close LTK Manager first if it is open).")\n',
     '    return (f"Parasite modlarını LTK Manager\'a taşıyamadı: {reason}.\\n\\n"\n'
     '            "Modların Parasite\'ta kalır ve eskisi gibi çalışır. Parasite bir sonraki açılışta tekrar dener "\n'
     '            "(LTK Manager açıksa önce onu kapat).")\n'),
    ("injection/mods/migration.py",
     '    return (f"Parasite could not back up your mods to your desktop: {why}.\\n\\n"\n'
     '            "Nothing was moved or deleted: your mods stay in Parasite and work as before, "\n'
     '            "and Parasite asks again the next time it starts.")\n',
     '    return (f"Parasite modlarını masaüstüne yedekleyemedi: {why}.\\n\\n"\n'
     '            "Hiçbir şey taşınmadı ya da silinmedi: modların Parasite\'ta kalır ve eskisi gibi çalışır, "\n'
     '            "Parasite bir sonraki açılışta yeniden sorar.")\n'),
    ("injection/mods/migration.py",
     '    return (f"Parasite moved {len(report.moved)} of your {total} mods into LTK Manager. These stay in Parasite and work "\n'
     '            f"as before, and Parasite tries to move them again the next time it starts:\\n\\n{failures}")\n',
     '    return (f"Parasite {total} modundan {len(report.moved)} tanesini LTK Manager\'a taşıdı. Şunlar Parasite\'ta kalır, "\n'
     '            f"eskisi gibi çalışır ve Parasite bir sonraki açılışta onları yeniden taşımayı dener:\\n\\n{failures}")\n'),

    # ---- installer.iss: Turkish is the installer's only language ----
    ("installer.iss", 'Name: "english"; MessagesFile: "compiler:Default.isl"',
     'Name: "turkish"; MessagesFile: "compiler:Languages\\Turkish.isl"'),
    ("installer.iss", '{cm:LaunchProgram,{#StringChange(MyAppName, \'&\', \'&&\')}} (as Administrator)',
     '{cm:LaunchProgram,{#StringChange(MyAppName, \'&\', \'&&\')}} (yönetici olarak)'),
    ("installer.iss", '#define MyAppDescription "Effortless skin changer for League of Legends"',
     '#define MyAppDescription "League of Legends için zahmetsiz skin değiştirici"'),
    ("installer.iss",
     "'Your settings, skin history and downloaded skins are kept unless you untick this.'",
     "'Bu kutunun işaretini kaldırmazsan ayarların, skin geçmişin ve indirilen skinler saklanır.'"),
    ("installer.iss", "'Keep my data in ' + _UserDataFolder()",
     "'Verilerim kalsın: ' + _UserDataFolder()"),
    ("installer.iss", "UninstallButton.Caption := 'Uninstall';", "UninstallButton.Caption := 'Kaldır';"),
    ("installer.iss", "'Uninstall {#MyAppName}'", "'{#MyAppName} kaldır'"),
    ("installer.iss", "'Tick the data you want to keep, then continue.'",
     "'Saklamak istediğin verileri işaretle, sonra devam et.'"),
    ("installer.iss",
     "      '{#MyAppName} and League of Legends are both currently running.'#13#10 +\n"
     "      'Please close both applications and try uninstalling again.',\n",
     "      '{#MyAppName} ve League of Legends şu anda açık.'#13#10 +\n"
     "      'İkisini de kapat ve kaldırmayı tekrar dene.',\n"),
    ("installer.iss",
     "      '{#MyAppName} is currently running.'#13#10 +\n"
     "      'Please close it completely (including the tray) and try uninstalling again.',\n",
     "      '{#MyAppName} şu anda açık.'#13#10 +\n"
     "      'Onu tamamen kapat (sistem tepsisinden de) ve kaldırmayı tekrar dene.',\n"),
    ("installer.iss",
     "      'League of Legends is currently running.'#13#10 +\n"
     "      'Please close League of Legends and try uninstalling again.',\n",
     "      'League of Legends şu anda açık.'#13#10 +\n"
     "      'League of Legends''i kapat ve kaldırmayı tekrar dene.',\n"),
    ("installer.iss",
     "          '{#MyAppName} could not finish cleaning up LTK Manager.'#13#10 +\n"
     "          'Some of your LTK Manager mods may still be turned off: turn them back on in LTK Manager.',\n",
     "          '{#MyAppName}, LTK Manager''ı temizlemeyi bitiremedi.'#13#10 +\n"
     "          'LTK Manager''daki bazı modların hâlâ kapalı olabilir: onları LTK Manager''da yeniden aç.',\n"),

    # ---- Pengu Loader's window (vendor/PenguLoader-1.1.6) ----
    # Turkish whatever is saved, and no language list to pick another
    ("vendor/PenguLoader-1.1.6/loader/App.xaml", 'Source="Languages/en-US.xaml"', 'Source="Languages/tr-TR.xaml"'),
    ("vendor/PenguLoader-1.1.6/loader/App.xaml.cs",
     '            if (!LanguageMap.ContainsKey(lang))\n                lang = "English";\n',
     '            lang = "Türkçe";  // Parasite is Turkish only\n'),
    ("vendor/PenguLoader-1.1.6/loader/Main/Config.cs", 'Get("Language", "English")', 'Get("Language", "Türkçe")'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml",
     '                <ComboBox\n'
     '                    ItemsSource="{Binding Source={x:Static root:App.Languages}}"\n'
     '                    SelectedItem="{Binding Path=(root:App.Language), Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"\n'
     '                    Margin="20,5"\n'
     '                    BorderThickness="1"\n'
     '                    BorderBrush="#33333333"\n'
     '                    HorizontalAlignment="Stretch" />\n',
     '                <!-- Parasite is Turkish only: no language list -->\n'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml", 'Text="Report a problem"', 'Text="Sorun bildir"'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml", 'Text="League path"', 'Text="League yolu"'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml", 'OffContent="OFF" OnContent="READY"',
     'OffContent="KAPALI" OnContent="HAZIR"'),
    ("vendor/PenguLoader-1.1.6/loader/Views/PluginsPage.xaml", 'Text="Loading..."', 'Text="Yükleniyor..."'),
    ("vendor/PenguLoader-1.1.6/loader/MainWindow.xaml", 'ToolTip="Change theme"', 'ToolTip="Temayı değiştir"'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml.cs",
     '"Failed to activate the core module globally, want to use symlink mode locally?"',
     '"Çekirdek modül genel olarak etkinleştirilemedi. Yerel sembolik bağlantı modu kullanılsın mı?"'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml.cs",
     '"Select Riot Games, League of Legends or LeagueClient folder."',
     '"Riot Games, League of Legends ya da LeagueClient klasörünü seç."'),
    ("vendor/PenguLoader-1.1.6/loader/Views/MainPage.xaml.cs",
     '"Your selected folder is not valid, please make sure it contains \\"LeagueClient.exe\\"."',
     '"Seçtiğin klasör geçersiz: içinde \\"LeagueClient.exe\\" olduğundan emin ol."'),
    ("vendor/PenguLoader-1.1.6/loader/Program.cs",
     '"32-BIT CLIENT DEPRECATION\\n\\nStarting with LoL patch 13.8, 32-bit Windows is no longer supported. '
     'Please upgrade your Windows to 64-bit."',
     '"32 BİT DESTEĞİ BİTTİ\\n\\nLoL 13.8 yamasından beri 32 bit Windows desteklenmiyor. '
     'Windows\'unu 64 bite yükselt."'),
    ("vendor/PenguLoader-1.1.6/loader/Main/Updater.cs",
     '"Please close your League of Legends Client to apply update."',
     '"Güncellemeyi uygulamak için League of Legends istemcisini kapat."'),
    ("vendor/PenguLoader-1.1.6/loader/Main/Updater.cs",
     '"Failed to download update. Please try downloading the update on GitHub releases page."',
     '"Güncelleme indirilemedi. Güncellemeyi GitHub\'daki sürümler sayfasından indirmeyi dene."'),
    ("vendor/PenguLoader-1.1.6/loader/Main/Updater.cs", '"Failed to check update.\\n"',
     '"Güncelleme kontrol edilemedi.\\n"'),

    # ---- client plugins: Turkish whatever the client's or a saved language ----
    ("utils/core/i18n.py",
     '    from config import get_config_option\n'
     '    setting = get_config_option("General", "language")\n'
     '    client_locale = getattr(shared_state, "current_locale", None) if shared_state else None\n'
     '    return resolve_language(setting, client_locale)\n',
     '    return TURKISH  # Parasite is Turkish only, whatever the client\'s or a saved language\n'),
    ("utils/core/i18n.py", 'AUTO = "auto"\nENGLISH = "en"\n',
     'AUTO = "auto"\nENGLISH = "en"\nTURKISH = "tr"\n'),
    ("utils/core/i18n.py",
     '    language = current_language(shared_state)\n    from config import get_config_option\n',
     '    language = current_language(shared_state)\n'),
    ("utils/core/i18n.py",
     '        "setting": get_config_option("General", "language") or AUTO,\n',
     '        "setting": TURKISH,\n'),
    ("utils/core/i18n.py", '        "languages": LANGUAGES,\n', '        "languages": {TURKISH: LANGUAGES[TURKISH]},\n'),
    ("Pengu Loader/plugins/PARASITE-I18n/index.js",
     'let state = { language: "en", setting: "auto", direction: "ltr", languages: { en: "English" }, strings: {} };',
     'let state = { language: "tr", setting: "tr", direction: "ltr", languages: { tr: "Türkçe" }, strings: {} };'),
    ("Pengu Loader/plugins/PARASITE-I18n/index.js", '      language: next.language || "en",\n',
     '      language: next.language || "tr",\n'),
    ("Pengu Loader/plugins/PARASITE-SettingsPanel/index.js",
     '      titleRow.appendChild(createLanguagePicker());\n',
     '      // Parasite is Turkish only: no language picker\n'),
]

TURKISH += [
    # ---- Rose's tests that read these texts ----
    ("test/test_installer_safety.py", r"MsgBox\(.*?turn them back on in LTK Manager.*?MB_OK", r"MsgBox\(.*?yeniden aç.*?MB_OK"),
    ("test/test_ltk_manager_dialog.py", 'self.assertEqual(action, "Set up path")', 'self.assertEqual(action, "Yolu ayarla")'),
    ("test/test_ltk_manager_dialog.py", '"never have to open it yourself"', '"senin hiç açman gerekmez"'),
    ("test/test_ltk_manager_dialog.py", '"is not LTK Manager"', '"LTK Manager değil"'),
    ("test/test_ltk_manager_dialog.py", '"could not save the path"', '"yolu cf.ini dosyasına kaydedemedi"'),
    ("pengu/tests/test_activation_warning.py", "self.assertIn('Diagnose Parasite startup', text)",
     f"self.assertIn('{DIAGNOSE}', text)"),
    ("utils/tests/test_tray_diagnostics.py", 'item.text == "Diagnosing Parasite startup..."',
     'item.text == "Başlangıç tanılanıyor..."'),
    ("utils/tests/test_tray_diagnostics.py", 'self.assertEqual(item.text, "Diagnose Parasite startup")',
     f'self.assertEqual(item.text, "{DIAGNOSE}")'),
    ("utils/tests/test_tray_diagnostics.py", 'self.assertIn("Could not save", ', 'self.assertIn("Tanılama kaydedilemedi", '),
    ("utils/tests/test_tray_diagnostics.py", 'self.assertIn("Reports saved", ', 'self.assertIn("Raporlar kaydedildi", '),
    ("utils/tests/test_startup_diagnostics.py", 'self.assertIn("missing", ', 'self.assertIn("eksik", '),
    ("utils/tests/test_startup_diagnostics.py", 'self.assertIn("code 1", ', 'self.assertIn("1 koduyla", '),
    ("utils/tests/test_startup_diagnostics.py", 'self.assertIn("timed out", ', 'self.assertIn("3 dakikada bitmedi", '),
    ("utils/tests/test_startup_diagnostics.py", 'self.assertIn("1 FAIL", ', 'self.assertIn("1 HATA", '),
    ("injection/tests/test_mod_migration.py", "Parasite mods backup ", "Parasite mod yedeği "),
    ("injection/tests/test_mod_migration.py", '"Parasite could not back up your mods to your desktop"',
     '"Parasite modlarını masaüstüne yedekleyemedi"'),
    ("injection/tests/test_mod_migration.py", '"Parasite moved 1 of your 2 mods"', '"Parasite 2 modundan 1 tanesini"'),
    ("injection/tests/test_mod_migration.py", '"100 MB is free there"', '"orada 100 MB boş"'),
    ("launcher/tests/test_mod_migration_sequence.py", "Parasite mods backup ", "Parasite mod yedeği "),
    ("launcher/tests/test_mod_migration_sequence.py", '"Parasite could not back up your mods to your desktop"',
     '"Parasite modlarını masaüstüne yedekleyemedi"'),
    ("launcher/tests/test_mod_migration_sequence.py", 'f"({migration.size_text(size)}, 120 GB free)"',
     'f"({migration.size_text(size)}, boş alan 120 GB)"'),
    ("launcher/tests/test_mod_migration_sequence.py", '"Backing up your mods to your desktop…"',
     '"Modların masaüstüne yedekleniyor…"'),
    ("launcher/tests/test_mod_migration_sequence.py", '"Moving your mods into LTK Manager (1/1): VO Korean"',
     '"Modların LTK Manager\'a taşınıyor (1/1): VO Korean"'),
    # The plugins' language: Turkish, whatever the client's or a saved one
    ("utils/tests/test_i18n.py",
     '    def test_payload_follows_the_client(self):\n'
     '        (self.directory / "ar.json").write_text(json.dumps({"Save": "حفظ"}), encoding="utf-8")\n'
     '        state = SimpleNamespace(current_locale="ar_AE")\n'
     '        with patch("config.get_config_option", return_value=None), \\\n'
     '                patch.object(i18n, "locales_dir", return_value=self.directory):\n'
     '            payload = i18n_payload(state)\n'
     '        self.assertEqual(payload["language"], "ar")\n'
     '        self.assertEqual(payload["setting"], "auto")\n'
     '        self.assertEqual(payload["direction"], "rtl")\n'
     '        self.assertEqual(payload["strings"], {"Save": "حفظ"})\n'
     '        self.assertEqual(payload["languages"], LANGUAGES)\n\n'
     '    def test_payload_uses_the_settings_choice(self):\n'
     '        (self.directory / "fr.json").write_text(json.dumps({"Save": "Enregistrer"}), encoding="utf-8")\n'
     '        state = SimpleNamespace(current_locale="ko_KR")\n'
     '        with patch("config.get_config_option", return_value="fr"), \\\n'
     '                patch.object(i18n, "locales_dir", return_value=self.directory):\n'
     '            payload = i18n_payload(state)\n'
     '        self.assertEqual(payload["language"], "fr")\n'
     '        self.assertEqual(payload["setting"], "fr")\n'
     '        self.assertEqual(payload["direction"], "ltr")\n',
     '    def test_payload_is_turkish_whatever_the_client(self):\n'
     '        (self.directory / "tr.json").write_text(json.dumps({"Save": "Kaydet"}), encoding="utf-8")\n'
     '        state = SimpleNamespace(current_locale="ar_AE")\n'
     '        with patch("config.get_config_option", return_value=None), \\\n'
     '                patch.object(i18n, "locales_dir", return_value=self.directory):\n'
     '            payload = i18n_payload(state)\n'
     '        self.assertEqual(payload["language"], "tr")\n'
     '        self.assertEqual(payload["setting"], "tr")\n'
     '        self.assertEqual(payload["direction"], "ltr")\n'
     '        self.assertEqual(payload["strings"], {"Save": "Kaydet"})\n'
     '        self.assertEqual(payload["languages"], {"tr": LANGUAGES["tr"]})\n\n'
     '    def test_payload_is_turkish_whatever_the_settings_choice(self):\n'
     '        (self.directory / "tr.json").write_text(json.dumps({"Save": "Kaydet"}), encoding="utf-8")\n'
     '        state = SimpleNamespace(current_locale="ko_KR")\n'
     '        with patch("config.get_config_option", return_value="fr"), \\\n'
     '                patch.object(i18n, "locales_dir", return_value=self.directory):\n'
     '            payload = i18n_payload(state)\n'
     '        self.assertEqual(payload["language"], "tr")\n'
     '        self.assertEqual(payload["setting"], "tr")\n'
     '        self.assertEqual(payload["direction"], "ltr")\n'),
]

# Rose's PARASITE-I18n texts with no Turkish in its tr.json
LOCALE_TR = {
    "Fix: LTK Manager closed while the game was running. Retry the next game. If it happens every game, report it with your Parasite logs.":
        "Çözüm: LTK Manager oyun sürerken kapandı. Bir sonraki maçta tekrar dene. Her maçta oluyorsa Parasite kayıtlarınla bildir.",
    "Fix: LTK Manager crashed. Retry the next game. If it crashes every game, report it with your Parasite logs.":
        "Çözüm: LTK Manager çöktü. Bir sonraki maçta tekrar dene. Her maçta çöküyorsa Parasite kayıtlarınla bildir.",
    "Fix: Parasite could not start the LTK patcher. Check that ltk_launcher.exe and LeagueToolFlop.dll are still in Parasite's tools folder: an antivirus may have removed them.":
        "Çözüm: Parasite LTK patcher'ı başlatamadı. ltk_launcher.exe ve LeagueToolFlop.dll'in Parasite'ın araçlar klasöründe durduğunu kontrol et: bir antivirüs onları silmiş olabilir.",
    "Fix: Parasite's launcher started LTK Manager but could not get into it. With err=5 (access denied) above, Windows or an antivirus refused it: add Parasite's folder to your antivirus exclusions, update Parasite, then retry. If Parasite runs as administrator through another Windows account than the one you are signed in with, make your own account an administrator instead.":
        "Çözüm: Parasite'ın başlatıcısı LTK Manager'ı açtı ama ona bağlanamadı. Yukarıda err=5 (erişim reddedildi) varsa Windows ya da bir antivirüs engelledi: Parasite'ın klasörünü antivirüsünün istisnalarına ekle, Parasite'ı güncelle, sonra tekrar dene. Parasite, oturum açtığın hesaptan başka bir Windows hesabıyla yönetici olarak çalışıyorsa bunun yerine kendi hesabını yönetici yap.",
    "Fix: Windows refused to start Parasite's ltk_launcher.exe because it is set to run as administrator, so LTK Manager did not start under explorer.exe. Parasite takes that setting off before it starts LTK Manager: retry the next game. If it happens again, untick \"Run this program as an administrator\" in the Compatibility tab of the Properties of ltk_launcher.exe, in Parasite's _internal\\injection\\tools folder (also under \"Change settings for all users\"), then restart Parasite.":
        "Çözüm: Windows, Parasite'ın ltk_launcher.exe dosyasını yönetici olarak çalışacak şekilde ayarlı olduğu için başlatmadı; bu yüzden LTK Manager explorer.exe altında açılmadı. Parasite bu ayarı LTK Manager'ı başlatmadan önce kaldırır: bir sonraki maçta tekrar dene. Yine olursa Parasite'ın _internal\\injection\\tools klasöründeki ltk_launcher.exe'nin Özellikler > Uyumluluk sekmesinde \"Bu programı yönetici olarak çalıştır\" işaretini kaldır (\"Tüm kullanıcılar için ayarları değiştir\" altında da), sonra Parasite'ı yeniden başlat.",
    "Fix: another program closed LTK Manager, most often an antivirus. Add Parasite's folder to its exclusions, then retry.":
        "Çözüm: LTK Manager'ı başka bir program kapattı, çoğunlukla bir antivirüs. Parasite'ın klasörünü onun istisnalarına ekle, sonra tekrar dene.",
    "Fix: close LTK Manager (also from the system tray), then retry. Parasite starts it with its bridge and closes it again after the game.":
        "Çözüm: LTK Manager'ı kapat (sistem tepsisinden de), sonra tekrar dene. Parasite onu kendi köprüsüyle açar ve maçtan sonra yine kapatır.",
    "Fix: free up some disk space, then retry.":
        "Çözüm: diskte biraz yer aç, sonra tekrar dene.",
    "Fix: free up some disk space, then retry. If it keeps happening, report it with your Parasite logs.":
        "Çözüm: diskte biraz yer aç, sonra tekrar dene. Olmaya devam ederse Parasite kayıtlarınla bildir.",
    "Fix: install LTK Manager, or set ltkManagerPath in Parasite's cf.ini to its ltk-manager.exe, then restart Parasite.":
        "Çözüm: LTK Manager'ı kur ya da Parasite'ın cf.ini dosyasındaki ltkManagerPath'i onun ltk-manager.exe dosyasına ayarla, sonra Parasite'ı yeniden başlat.",
    "Fix: reinstall Parasite (the files are part of every install). If an antivirus removed them, restore the files or add Parasite's folder to its exclusions, then restart Parasite.":
        "Çözüm: Parasite'ı yeniden kur (bu dosyalar her kurulumda gelir). Bir antivirüs onları sildiyse dosyaları geri yükle ya da Parasite'ın klasörünü onun istisnalarına ekle, sonra Parasite'ı yeniden başlat.",
    "Fix: untick \"Run this program as an administrator\" in the Compatibility tab of the Properties of each program listed (for one marked \"all users\", under \"Change settings for all users\"), then restart League. For a program that no longer exists, delete its entry under AppCompatFlags\\Layers with regedit.":
        "Çözüm: listelenen her programın Özellikler > Uyumluluk sekmesinde \"Bu programı yönetici olarak çalıştır\" işaretini kaldır (\"tüm kullanıcılar\" diye işaretli olanlar için \"Tüm kullanıcılar için ayarları değiştir\" altında), sonra League'i yeniden başlat. Artık var olmayan bir program için regedit ile AppCompatFlags\\Layers altındaki kaydını sil.",
    "Fix: untick \"Run this program as an administrator\" in the Compatibility tab of the Properties of ltk_launcher.exe, in Parasite's _internal\\injection\\tools folder (for one marked \"all users\", under \"Change settings for all users\"), then restart Parasite.":
        "Çözüm: Parasite'ın _internal\\injection\\tools klasöründeki ltk_launcher.exe'nin Özellikler > Uyumluluk sekmesinde \"Bu programı yönetici olarak çalıştır\" işaretini kaldır (\"tüm kullanıcılar\" diye işaretliyse \"Tüm kullanıcılar için ayarları değiştir\" altında), sonra Parasite'ı yeniden başlat.",
    "LTK Manager is not installed": "LTK Manager kurulu değil",
    "LTK Manager rejected this mod, but Parasite could not remove it. It is still in your library.":
        "LTK Manager bu modu reddetti ama Parasite onu kaldıramadı. Mod hâlâ kütüphanende.",
    "LTK Manager rejected {name}, but Parasite could not remove it. It is still in your library.":
        "LTK Manager {name} modunu reddetti ama Parasite onu kaldıramadı. Mod hâlâ kütüphanende.",
    "Parasite bridge files are missing": "Parasite'ın köprü dosyaları eksik",
    "Parasite's launcher is set to run as administrator": "Parasite'ın başlatıcısı yönetici olarak çalışacak şekilde ayarlı",
    "The mod could not be installed into LTK Manager": "Mod LTK Manager'a kurulamadı",
    "What happened: LTK Manager refused the mod import.": "Ne oldu: LTK Manager modu içe aktarmayı reddetti.",
    "What it means: Parasite applies skins through LTK Manager, which was not found on this PC.":
        "Anlamı: Parasite skinleri LTK Manager üzerinden uygular, ama LTK Manager bu bilgisayarda bulunamadı.",
    "What it means: Parasite could not install the mod for the selected skin.":
        "Anlamı: Parasite seçilen skinin modunu kuramadı.",
    "What it means: Parasite needs ltk_launcher.exe and LeagueToolFlop.dll in its tools folder to drive LTK Manager.":
        "Anlamı: Parasite'ın LTK Manager'ı yönetebilmesi için araçlar klasöründe ltk_launcher.exe ve LeagueToolFlop.dll gerekiyor.",
    "What it means: Windows' compatibility settings run Parasite's ltk_launcher.exe as administrator, so Windows refuses to start it for your Windows account, LTK Manager does not start under explorer.exe and its patcher refuses the skins. Parasite could not take that setting off by itself: {detail}":
        "Anlamı: Windows'un uyumluluk ayarları Parasite'ın ltk_launcher.exe dosyasını yönetici olarak çalıştırıyor; bu yüzden Windows onu senin hesabın için başlatmıyor, LTK Manager explorer.exe altında açılmıyor ve patcher'ı skinleri reddediyor. Parasite bu ayarı kendisi kaldıramadı: {detail}",
}

# Rose's tr.json: "Rose'u" became "Parasite'u" (Parasite takes back vowels: Parasite'ı, as the hub
# writes it), and its texts name the tray item by its English name
TR_JSON_FIXES = [
    ("Parasite'un", "Parasite'ın"),
    ("Parasite'u", "Parasite'ı"),
    ('\\"Open Logs folder\\"', f'\\"{LOG_FOLDER}\\"'),
]


def apply_turkish(tree, read_text, write_text):
    """Apply TURKISH and TR_JSON_FIXES to the rebuilt tree; fail on any text that is gone."""
    failures = []
    for rel, old, new in TURKISH:
        path = tree / rel
        if not path.exists():
            failures.append(f"{rel}: file is gone")
            continue
        raw = read_text(path)
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        if old not in text:
            failures.append(f"{rel}: English text not found:\n{old[:200]}")
            continue
        text = text.replace(old, new)
        write_text(path, text.replace("\n", "\r\n") if crlf else text)
    tr_json = tree / "Pengu Loader/plugins/PARASITE-I18n/locales/tr.json"
    raw = read_text(tr_json)
    for old, new in TR_JSON_FIXES:
        if old not in raw:
            failures.append(f"tr.json: {old!r} not found")
        raw = raw.replace(old, new)
    write_text(tr_json, raw)
    if failures:
        raise SystemExit("[sync] Parasite's Turkish texts no longer fit Rose's code:\n\n" + "\n\n".join(failures))
