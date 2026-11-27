# Balluff tag logger: Windows station setup

## Files

| File | What it does |
|---|---|
| `bisc600.exe` | The program. Needs no Python install. |
| `start_sfc_logging.bat` | Double-click to start. Set to `COM1` (the station PC's port); edit `COM_PORT` if yours differs. |
| `list_com_ports.bat` | Double-click to see which COM port the reader is on. |
| `C:\balluff\sfc_log.txt` | The output. Created (with its folder) on the first read and **overwritten on every read** with the latest tag. Change `LOG_FILE` in `start_sfc_logging.bat` to put it elsewhere. |

## First-time setup

1. Copy this folder to the station PC, e.g. `C:\balluff`.
2. Plug in the USB-RS232 adapter. Windows Update normally installs the Prolific driver by itself.
   If it shows with a yellow warning in Device Manager, install the PL2303 driver from Prolific's website.
3. The batch file is set to `COM1`. If the reader is on a different port, double-click
   `list_com_ports.bat`, then right-click `start_sfc_logging.bat` → **Edit** and change `COM_PORT`.
4. Double-click `start_sfc_logging.bat`. Put a tagged part on the head; the
   `TagFixID=... TagPartNo=... TagSFC=...` line appears in about half a second.

To start it with Windows: press Win+R, type `shell:startup`, and put a shortcut to `start_sfc_logging.bat` in that folder.

## Output format

The file always holds just the most recent tag (it is replaced, never appended to):

```
TagFixID=139
TagPartNo=LV34900
TagSFC=AB593236
```

Only the first 64 bytes of the tag are read, which is why it takes ~0.5 s rather than the ~10 s a full 2 KB read takes.
The old full-tag hex log is still available: `bisc600.exe --port COM1 sfc --format hex`.

## Troubleshooting

| Message | Meaning |
|---|---|
| `could not open port 'COM3'` | Wrong `COM_PORT`, adapter unplugged, or another program has the port open. |
| `timed out waiting for … bytes` | No reply from the reader: check its 24 V supply and the RS232 wiring. If it still doesn't answer, switch the reader's 24 V off and on. |
| `tag removed before the read finished - not recorded` | Part was taken away mid-read. Put it back. |
| Windows Defender / SmartScreen warning | Common for unsigned in-house .exe files. Choose "More info → Run anyway", or ask IT to allow it. |

## Command line

```
bisc600.exe --port COM1 status
bisc600.exe --port COM1 -v read 0 64 --head 1
bisc600.exe --port COM1 sfc --format tag --file C:\balluff\sfc_log.txt   (what the .bat runs)
bisc600.exe --port COM1 sfc --format hex      (old behaviour: append the whole tag as hex, ~10 s)
bisc600.exe decode-log old_log.txt            (turn old hex logs into Tag... lines)
bisc600.exe -h
```
