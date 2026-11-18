# Parasite Offline

Parasite Offline lets players appear offline to their friends. It is
[Deceive](https://github.com/molenzwiebel/Deceive) by molenzwiebel, renamed to
Parasite and licensed, like Deceive, under the GNU GPL v3 (`src/LICENSE`). Parasite
itself stays MIT; Parasite Offline ships next to it as a separate program.

Changes from Deceive (all made by `build_offline.py`):

- Everything players see says Parasite instead of Deceive.
- No welcome messages in chat, no tray balloon and no update prompt on start.
- Settings live in `%APPDATA%\Parasite Offline`.

`src/` is the modified source of the shipped `ParasiteOffline.exe`, as the GPL
requires. To rebuild from a newer Deceive:

```
git clone https://github.com/molenzwiebel/Deceive.git
python parasite/offline/build_offline.py Deceive
```

Parasite starts League through it (`overlay/launcher/parasite_offline.py`). Players
switch between online and offline from the Parasite Offline tray icon, or by
messaging the "Parasite Active!" friend `online`, `offline` or `mobile`.
