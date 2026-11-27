# Context handover: Balluff BIS008U RFID reader

Handover from a Claude chat session (27 Nov 2026). Read this file first, then `bisc600.py`.

## Goal

Read (and later write) Balluff LF RFID tags using a **Balluff BIS008U** processor connected to a PC over RS232. The PC may be **Windows**. End use is not yet decided (e.g. logging tag IDs / kit tracking): ask David before designing anything beyond the reader.

## Hardware

| Item | Detail |
|---|---|
| Processor | **BIS008U** = BIS C-600-007-650-00-KL1 |
| Frequency | LF, 70/455 kHz (Balluff BIS C system) |
| Interface | RS232, **Balluff protocol "007"** (ASCII telegrams) |
| Heads | Up to 2 external BIS C read/write heads (the "650" variant has no built-in head; check one is fitted) |
| Tags | **Balluff BIS C-1xx code carriers only.** Not ISO 14443/15693/EM4100; phones and generic USB readers can't read them |
| Power | 24 V DC (19.2–28.8 V, ≤400 mA) on +VS / –VS |
| Connection | 19-pin terminal strip; upper row: +VS, –VS, TxD, RxD, COM; lower row: +VS, –VS, OUT1–4 (PNP, 20 mA), +IN/–IN |
| PC link | USB to **true RS232** adapter (not TTL). Wire TxD↔RxD crossed, COM to GND. Prefer FTDI-based adapters on Windows |
| Handshake | Jumper ("shunt"): SHORT = no CTS handshake (factory default), OPEN = RTS/CTS |

## Documentation

- Product page: https://www.balluff.com/en-gb/products/BIS008U
- **Protocol manual (German only):** BIS C-600-007, doc 836905
  https://assets.balluff.com/WebBinary1/MAN_BIS_C_600_007_DE_0704_DRW_836905_AA_000.pdf
- English version of a near-identical manual (BIS C-6_0 RS232) on ManualsLib: https://www.manualslib.de/manual/909069/ (English protocol pages around 55–57)
- Head/mounting manual (no protocol info): MAN_BIS_C_6_LESEK_DE_EN_G21_DRW_640104_02_000.pdf
- Balluff UK: +44 1606 812777

## Protocol summary (from the 836905 manual)

**Serial:** 9600 baud, 8 data bits, **even parity**, 1 stop bit (factory default). Changed only with Balluff's legacy `BISC600A.EXE` tool.

**Rules:** ≥300 ms between telegrams; no continuous polling; after `Q` (reset) wait ≥1600 ms.

**BCC:** XOR of every byte in the block (BCC excluded). Enabled by default (alternatives: CR, CR end char, LF+CR end char).
- Command telegram: BCC = XOR(command chars)
- Write data block: BCC = XOR(**STX** + data)
- Read response: BCC = XOR(data) (no STX)
These were verified against all the manual's worked examples (`bisc600.py selftest`).

**Field notation:** A3–A0 start address (4 ASCII decimal digits, 0000–8191); L3–L0 byte count (0001–8192); K head ('1'/'2'); B page size ('0' = 64 byte, '1' = 32 byte).

| Cmd | Host sends | Unit replies | Then |
|---|---|---|---|
| `L` read (head + page) | `L A3..A0 L3..L0 K B BCC` | ACK '0' | host STX → unit `D1..Dn BCC` |
| `P` write (head + page) | `P A3..A0 L3..L0 K B BCC` | ACK '0' | host `STX D1..Dn BCC` → unit ACK '0' |
| `R` read (current head) | `R A3..A0 L3..L0 BCC` | ACK '0' when data ready | host STX → unit `D1..Dn BCC` |
| `W` write (current head) | `W A3..A0 L3..L0 BCC` | ACK '0' | as P |
| `C` write constant | `C A3..A0 L3..L0 K B BCC` | ACK '0' | host `STX D BCC` → ACK '0' |
| `H` select head | `H 1`/`H 2`/`H T` + BCC | ACK '0' (with T: '1'/'2' = head with tag) | |
| `H?` find once | `H ? BCC` | ACK '0', then `H head D1..D4 BCC` | `H ? 0000` if none |
| `H!` find continuous | `H ! BCC` | ACK '0', then `H head D1..D4 BCC` once a tag appears | |
| `B` outputs | `B <id> BCC` (00/10/20/30 clear, 01/11/21/31 set, A0/A1 all) | ACK '0' | `BAO` reads states |
| `S` status | `S BCC` | `S <char> BCC` (space = idle, R/W/L/P/H busy) | |
| `Q` reset | `Q BCC` | `Q BCC` | wait 1600 ms |
| `Z` CRC16 init | like `P` | | CRC mode: 2 bytes/page used |

Worked examples: `L0013012820` → BCC 'G' (0x47); `H1` → 'y'; `H?` → 'w'.

**Error codes** (NAK + char): 1 no tag · 2 read error · 3 tag removed during read · 4 write error · 5 tag removed during write · 6 interface (parity/stop) · 7 format/range · 8 BCC wrong · 9 cable break / head missing · A/B/C operation already running · E CRC error on tag · I EEPROM error.

**Tags:** 32-byte pages: BIS C-1xx-02/-03/-04/-05. 64-byte pages: -10/-11/-30/-32. Capacities 128 B – 8 KB.

**Timing:** static read ~110 ms (32 B page) / 220 ms (64 B page) + per extra page; tag detect ~150 ms; supervise reads with a 15 s timeout, writes 30–60 s.

## Current state of the code

`bisc600.py`: Python 3 + pyserial command-line client, single file.
- Commands: `selftest`, `ports`, `status`, `reset`, `head`, `find`, `read`, `write`, `watch`, plus `-v` for a raw byte trace.
- Defaults: COM3 on Windows, /dev/ttyUSB0 elsewhere; `--block 32|64`; `--head 1|2`.
- `selftest` passes (BCC checks). **Not yet tested against real hardware.**

Windows setup: install Python 3 (add to PATH) → `pip install pyserial` → `python bisc600.py ports` → `python bisc600.py --port COMx -v find`.

## Open questions / verify on the bench

1. ~~**ACK format**~~ **Settled 27 Nov 2026:** two bytes, 0x06 then '0'. The code now requires exactly that.
2. **9-pin PC cable pinout:** the table was garbled when extracted. Check against the PDF diagram.
3. ~~Head / tag type~~ **Settled 27 Nov 2026:** head 1 fitted and working; test tag is a BIS C-122-11 (64-byte pages, labelled "17 BALLUFF BIS0015").
4. ~~Serial settings~~ **Settled 27 Nov 2026:** unit is on the factory 9600 8E1.
5. **End use (David, 27 Nov 2026):** each part's tag carries its serial number, called an **"SFC"** (almost certainly MES jargon for Shop Floor Control number, as in SAP ME / Digital Manufacturing). The reader reads the SFC, which is logged whenever the part is inspected or worked on. Details still to agree: SFC location/format on the tag, who writes it, log destination, fields per event. Earlier packaging notes: Possible next steps: package as a Windows `.exe` (PyInstaller, build on Windows), port to TypeScript/Node with `serialport` if it needs to join a Node project, or log reads to CSV.

## Suggested next steps

1. Run `-v status`, then `-v find`, then `-v read 0 16` against the hardware and record the raw traces here.
2. Settle the ACK format and tidy `_expect_ack`.
3. Agree the end use with David before adding features. Leave `write` alone until reads are reliable.

## Bench log

**27 Nov 2026, Mac, Prolific PL2303GT adapter (`/dev/cu.PL2303G-USBtoUART1110`, needs the PL2303Serial driver from the Mac App Store)**

`-v status`:
```
>> 53 53      'S' + BCC
<< 53 20 73   'S' ' ' 's'
```
Link confirmed at 9600 8E1, reply BCC valid. Idle state is a **space (0x20)**, not '_' as first read from the manual.

`-v find` (tag on head 1):
```
>> 48 21 69               'H!' + BCC
<< 06 30                  <ACK> '0'
<< 48 31 48 00 00 00 31   'H' head 1, data 48 00 00 00, BCC valid
```
ACK confirmed as two bytes (0x06 '0'). First 4 bytes of the test tag: `48 00 00 00`.

`-v read 0 16 --head 1 --block 64` (BIS C-122-11):
```
>> 4c 30 30 30 30 30 30 31 36 31 30 4a   'L0000001610' + BCC 'J'
<< 06 30                                 <ACK> '0'
>> 02                                    STX
<< 48 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 48   16 data bytes + BCC
```
Read-response BCC = XOR(data) only (0x48); with STX it would be 0x4A. Code now accepts only XOR(data).
Tag contents: `48` ('H') at address 0, rest zero: effectively blank.

`-v watch --length 16 --head 1`: tag placed and removed 3 times, each reported exactly once:
```
09:19:25  head 1  48 00 00 … 00
09:19:29  tag removed
09:19:33  head 1  48 00 00 … 00
09:19:37  tag removed
09:19:40  head 1  48 00 00 … 00
09:19:44  tag removed
```
Cycle on the wire: `H!` (blocks until a tag) → `L…` read → `H?` once a second while present. No-tag reply confirmed as `48 3f 30 30 30 30 77` ('H?0000' + BCC).

### Lockup found and fixed (27 Nov 2026)

Stopping the original `watch` while `H!` (find continuous) was pending, with no tag present, left the unit **answering nothing**: `S` and even `Q` timed out. The head's tag LED still worked. Replugging the USB adapter did not help; **only cycling the reader's 24 V cleared it.**

Fix: the code no longer sends `H!` at all. `find` waits by sending `H?` once a second (`wait_for_tag`, default timeout 60 s, `find --once` checks once); `watch` does the same. Each `H?` is answered immediately, so Ctrl+C, a timeout or a crash can't leave a command pending. Re-tested: `watch` interrupted while waiting with no tag exits cleanly, and `status` straight after returns idle.

Re-test of the new `watch` (H? polling) with the tag on head 1, moved on/off 4 times: each arrival read once, each removal reported once (09:26:25 → 09:26:55), no `H!` on the wire. Stopped with SIGINT; `status` → idle afterwards.

## SFC logging (`sfc` command, added 27 Nov 2026)

`python bisc600.py --port COMx sfc [--file sfc_log.txt] [--addr 0] [--length 32]`

On each tag arrival: read `--length` bytes from `--addr`, strip trailing NUL/0xFF/space padding, and append one line `YYYY-MM-DD HH:MM:SS<TAB>SFC` to the file (opened and closed per line, so nothing is lost on a stop). Non-printable data is logged as `HEX:…`; blank tags are not logged. One line per arrival: the same tag removed and replaced logs again.

**Unverified assumptions:** the SFC is ASCII text starting at address 0 and fits in 32 bytes. No real SFC tag was available; check one and adjust `--addr` / `--length` (or the defaults).

First `write` and end-to-end `sfc` test (27 Nov 2026), BIS C-122-11 on head 1:
```
>> 50 30 30 30 30 30 30 31 33 31 30 53          'P0000001310' + BCC 'S'
<< 06 30                                        <ACK> '0'
>> 02 54 45 53 54 2d 53 46 43 2d 30 30 30 31 43 STX 'TEST-SFC-0001' + BCC 'C'
<< 06 30                                        <ACK> '0'
```
Write-data BCC = XOR(STX + data) confirmed. Read-back: `TEST-SFC-0001` then zeros. `sfc` logged `2026-11-27 09:37:17<TAB>TEST-SFC-0001`. The test tag now holds this test SFC (the old 'H' at address 0 was overwritten).
A write without a tag present returns NAK '1' and writes nothing.

### Tag capacity and full-tag logging (27 Nov 2026)

BIS C-122-11 capacity probed: address 2047 reads, 2048 gives NAK '2' → **2048 bytes**. A full 2048-byte read takes **~10 s** (`L`, 64-byte pages, 9600 baud).
Test tag contents: mostly `FF` (unwritten) and `00`, plus `harry` at address 37 and `CE` at 256: earlier test data, no SFC.

Since the real SFC layout is unknown, **`sfc` now logs the whole tag by default**: one line per read, `YYYY-MM-DD HH:MM:SS<TAB><4096 hex chars>`. It prints "reading, hold the part on the head" on arrival and "tag removed before the read finished - not recorded" if pulled early. `--format sfc --length 32` restores decoded-SFC logging once the layout is known.

## Windows packaging (27 Nov 2026)

`windows/build.bat`, run on a Windows PC with python.org Python 3: creates `.venv-win`, installs pyserial + PyInstaller, runs the tests, builds `dist\bisc600.exe` (one file, console), and copies `start_sfc_logging.bat` (edit `COM_PORT`), `list_com_ports.bat` and the station `README.md` into `dist\`. Copy `dist\` to the station PC; it doesn't need Python.
`.bat` files are CRLF (enforced by `.gitattributes`). A trial PyInstaller build on the Mac ran `selftest`, `ports` and `status` against the reader. **The Windows build itself hasn't been run yet.**
GitHub: `git@github.com:davidosullivankedos/balluff-rfid-reader.git`. `.github/workflows/build-windows.yml` builds and smoke-tests the exe on a Windows runner for every push to `main`; download it from the run's **Artifacts** (`balluff-tag-logger-windows`).

Log location: on Windows `sfc` defaults to **`C:\balluff\sfc_log.txt`** (folder created if missing); elsewhere `sfc_log.txt` in the current folder. Override with `--file` or `LOG_FILE` in `start_sfc_logging.bat`.

### ASCII log format (27 Nov 2026)

Harry (who now has the unit) asked for text, not hex. `sfc` now defaults to `--format ascii`: whole tag read, printable runs (0x20–0x7E) kept, everything else dropped, runs joined with one space, e.g. `TEST-SFC-0001 harry Z` for the bench tag. `--format hex` keeps the old full-hex line. Waiting on an example from Harry (a hex log line for a real part, plus the SFC it should show) to pin down the SFC's address, length and encoding, then cut the read down from ~10 s.

Blank tags are logged too (a valid read): the line is `date time<TAB>` with an empty value; the window shows `(blank tag)`.
