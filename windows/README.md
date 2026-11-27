# Balluff tag logger: Windows station setup

## Files

| File | What it does |
|---|---|
| `bisc600.exe` | The program. Needs no Python install. |
| `start_sfc_logging.bat` | Double-click to start logging. **Edit `COM_PORT` in it first.** |
| `list_com_ports.bat` | Double-click to see which COM port the reader is on. |
| `sfc_log.txt` | Created on the first read, next to the .bat. One line per read. |

## First-time setup

1. Copy this folder to the station PC, e.g. `C:\BalluffLogger`.
2. Plug in the USB-RS232 adapter. Windows Update normally installs the Prolific driver by itself.
   If it shows with a yellow warning in Device Manager, install the PL2303 driver from Prolific's website.
3. Double-click `list_com_ports.bat` and note the port, e.g. `COM4`.
4. Right-click `start_sfc_logging.bat` → **Edit**, set `COM_PORT=COM4`, save.
5. Double-click `start_sfc_logging.bat`. Put a tagged part on the head and keep it there until
   "bytes logged" appears (about 10 s for a full 2 KB tag).

To start it with Windows: press Win+R, type `shell:startup`, and put a shortcut to `start_sfc_logging.bat` in that folder.

## Log format

```
2026-11-27 09:39:52<TAB>544553542D5346432D303030310000…
```

Date and time, a tab, then every byte read from the tag as hex (4096 characters for a 2 KB tag).

## Troubleshooting

| Message | Meaning |
|---|---|
| `could not open port 'COM3'` | Wrong `COM_PORT`, adapter unplugged, or another program has the port open. |
| `timed out waiting for … bytes` | No reply from the reader: check its 24 V supply and the RS232 wiring. If it still doesn't answer, switch the reader's 24 V off and on. |
| `tag removed before the read finished - not recorded` | Part was taken away during the ~10 s read. Put it back. |
| Windows Defender / SmartScreen warning | Common for unsigned in-house .exe files. Choose "More info → Run anyway", or ask IT to allow it. |

## Command line

```
bisc600.exe --port COM4 status
bisc600.exe --port COM4 -v read 0 16 --head 1
bisc600.exe --port COM4 sfc --format sfc --length 32    (log decoded SFC text instead of hex)
bisc600.exe -h
```
