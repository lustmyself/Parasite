# Troubleshooting

Start with the **Troubleshooting** panel in Parasite's settings: it names most problems and how to fix them. If that doesn't help, collect a diagnostic report and open a [bug report](https://github.com/lustmyself/Parasite/issues/new/choose).

## Diagnostic report

Use it when Parasite is missing from the League client or skins don't load.

1. Reproduce the problem, and leave Parasite and League open.
2. Right-click Parasite's tray icon and choose **Diagnose Parasite startup**.
3. A progress window shows the run (**Run in background** hides it). The report folder opens when it is done.

Reports are saved under `%LOCALAPPDATA%\Parasite\logs\diagnostics\Parasite-Diagnostics-<timestamp>-<id>`, apart from the ordinary logs. **Open Logs folder** in the progress window opens them. Each run has:

| File | Content |
| --- | --- |
| `report.txt` | The readable report |
| `report.json` | The same checks, for tools |
| `collector-status.txt` | Whether the run finished, failed, or timed out (after three minutes) |

The collector (Windows PowerShell 5.1, bundled with Parasite) checks Windows and runtime differences, Pengu Loader's configuration and activation, the patcher files, relevant security events, process privileges, the bridge connection, and recent error excerpts. It only reads: it repairs nothing, doesn't restart League, and doesn't change security settings. The only network call is a clock check against `time.windows.com`. Reports are never uploaded.

When reading a report:

- `UNKNOWN` means a check couldn't run.
- A warning is a possible cause, not proof that the injection failed.
- Common credentials and profile paths are redacted, but read the report before you share it.

To run the collector by hand, run `assets\diagnostics\Diagnose-Parasite.ps1` from Parasite's folder. `-SkipNetworkChecks` skips the clock check.

## Parasite won't start after an interrupted update

Parasite stages each update beside the installation and keeps the previous version there.

1. Close any Parasite windows.
2. Run `C:\Program Files\Parasite.update\Recover-Parasite.cmd` as administrator. For a custom install folder, it is in the sibling folder named `<install folder>.update`.
3. Open Parasite again.

`update.log` in the same folder records what the recovery did.

Automatic updates keep the uninstaller you already have. To get the latest uninstall rules, install with the newest setup executable. Uninstalling can leave files Parasite didn't install, and the update folder while it holds a recovery snapshot.
