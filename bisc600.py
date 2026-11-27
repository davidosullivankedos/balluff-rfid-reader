#!/usr/bin/env python3
"""
Balluff BIS C-600-007 (order code BIS008U) RS232 client.

Protocol source: Balluff manual BIS C-600-007 (doc 836905, German, 07/04).
Factory serial settings: 9600 baud, 8 data bits, even parity, 1 stop bit.
Factory end-of-telegram: BCC (XOR of all bytes in the block).

Windows setup:
  1. Install Python 3 from python.org (tick "Add python.exe to PATH").
  2. pip install pyserial
  3. Plug in the USB-RS232 adapter, then:  python bisc600.py ports
  4. Use the COM port it shows, e.g.:     python bisc600.py --port COM4 -v find

Usage examples:
  python bisc600.py --port /dev/ttyUSB0 selftest          # check BCC maths, no hardware
  python bisc600.py --port /dev/ttyUSB0 status
  python bisc600.py --port /dev/ttyUSB0 head 1
  python bisc600.py --port /dev/ttyUSB0 find               # wait (up to 60 s) for a tag, print first 4 bytes
  python bisc600.py --port /dev/ttyUSB0 read 0 16          # read 16 bytes from address 0
  python bisc600.py --port /dev/ttyUSB0 read 0 16 --head 2 --block 32
  python bisc600.py --port /dev/ttyUSB0 write 0 "HELLO"    # write ASCII
  python bisc600.py --port /dev/ttyUSB0 write 0 48454C4C4F --hex
  python bisc600.py --port COM3 watch --length 8           # loop: read 8 bytes whenever a tag shows up
  python bisc600.py --port COM3 sfc                        # log each tag read: "<date time>\t<text on tag>" per line
  python bisc600.py --port COM3 sfc --format hex           # log every byte as hex instead
  python bisc600.py --port COM3 sfc --format sfc --length 32   # log decoded SFC text instead
  python bisc600.py --port COM1 sfc --format tag --file C:\\balluff\\sfc_log.txt
        # on each tag: OVERWRITE the file with TagFixID= / TagPartNo= / TagSFC= (reads 64 bytes, ~0.5 s)
  python bisc600.py decode-log sfc_log.txt                     # decode old hex logs to the Tag... format

Add -v to see every raw byte on the wire (useful for the first test).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from functools import reduce

try:
    import serial  # pyserial
except ImportError:  # selftest still works without it
    serial = None

STX = 0x02
ACK = 0x06
NAK = 0x15

ERRORS = {
    "1": "No data carrier (tag) in front of the head",
    "2": "Read error",
    "3": "Tag removed during read",
    "4": "Write error (data may be partly written)",
    "5": "Tag removed during write",
    "6": "Interface error (parity / stop bit) - check serial settings",
    "7": "Format error (bad command, or address/length out of range)",
    "8": "BCC wrong",
    "9": "Cable break or head not connected",
    "A": "Read already in progress",
    "B": "Write already in progress",
    "C": "Head switch already in progress",
    "E": "CRC error on tag",
    "I": "EEPROM error",
}

# Where `sfc` appends its log unless --file says otherwise.
DEFAULT_LOG = r"C:\balluff\sfc_log.txt" if sys.platform == "win32" else "sfc_log.txt"

MIN_GAP_S = 0.30  # manual: minimum 300 ms between telegrams, no continuous polling


def bcc(data: bytes) -> int:
    """Block check character: XOR of every byte."""
    return reduce(lambda a, b: a ^ b, data, 0)


class BisError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"NAK {code}: {ERRORS.get(code, 'unknown error')}")


@dataclass
class TagHit:
    head: int
    first4: bytes


class BisC600:
    def __init__(self, port: str, baud: int = 9600, verbose: bool = False, timeout: float = 15.0):
        if serial is None:
            sys.exit("pyserial is not installed: pip install pyserial")
        self.verbose = verbose
        self.timeout = timeout
        self._last = 0.0
        self.ser = serial.Serial(
            port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )

    # ---- low level -------------------------------------------------------
    def close(self):
        self.ser.close()

    def _log(self, direction: str, data: bytes):
        if self.verbose:
            print(f"{direction} {data.hex(' ')}  {data!r}", file=sys.stderr)

    def _send(self, data: bytes):
        self._log(">>", data)
        self.ser.write(data)
        self.ser.flush()

    def _read_exact(self, n: int, timeout: float | None = None) -> bytes:
        deadline = time.monotonic() + (timeout or self.timeout)
        buf = bytearray()
        while len(buf) < n:
            if time.monotonic() > deadline:
                self._log("<<", bytes(buf))
                raise TimeoutError(f"timed out waiting for {n} bytes, got {len(buf)}")
            buf += self.ser.read(n - len(buf))
        self._log("<<", bytes(buf))
        return bytes(buf)

    def _read_optional(self, n: int, timeout: float) -> bytes:
        """Like _read_exact, but returns whatever arrived (possibly nothing) instead of raising."""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while len(buf) < n and time.monotonic() < deadline:
            buf += self.ser.read(n - len(buf))
        if buf:
            self._log("<<", bytes(buf))
        return bytes(buf)

    def _wait_gap(self):
        dt = time.monotonic() - self._last
        if dt < MIN_GAP_S:
            time.sleep(MIN_GAP_S - dt)

    def _send_telegram(self, body: str):
        """Respect the 300 ms gap, drop stale input, send command + BCC."""
        self._wait_gap()
        self.ser.reset_input_buffer()
        raw = body.encode("ascii")
        self._send(raw + bytes([bcc(raw)]))

    def _command(self, body: str, timeout: float | None = None):
        """Send command + BCC, then expect <ACK>'0' or <NAK><err>."""
        self._send_telegram(body)
        self._expect_ack(timeout)

    def _read_ack(self, timeout: float | None = None) -> str:
        """Read <ACK><char> and return the char; raise BisError on <NAK><code>.

        Bench-confirmed 27 Nov 2026: the positive reply is two bytes, 0x06 then '0'.
        """
        b = self._read_exact(1, timeout)[0]
        if b == NAK:
            raise BisError(chr(self._read_exact(1)[0]))
        if b != ACK:
            raise RuntimeError(f"expected ACK/NAK, got 0x{b:02x}")
        return chr(self._read_exact(1)[0])

    def _expect_ack(self, timeout: float | None = None):
        c = self._read_ack(timeout)
        if c != "0":
            raise RuntimeError(f"unexpected ACK char {c!r}")

    def _done(self):
        self._last = time.monotonic()

    # ---- commands --------------------------------------------------------
    def select_head(self, head: str = "1") -> int:
        """'1', '2' or 'T' (both). Returns the head that has a tag when 'T', else 0.

        The manual says 'T' answers with '1'/'2' where the '0' would normally be.
        Most likely <ACK>'1', but not yet bench-tested, so a head number arriving
        after <ACK>'0' is accepted too.
        """
        try:
            self._send_telegram(f"H{head}")
            c = self._read_ack()
            if head != "T":
                if c != "0":
                    raise RuntimeError(f"unexpected ACK char {c!r}")
                return 0
            if c in "12":
                return int(c)
            if c == "0":
                extra = self._read_optional(1, 0.3)  # head number may follow the '0'
                if extra and chr(extra[0]) in "12":
                    return int(chr(extra[0]))
                return 0
            raise RuntimeError(f"unexpected reply byte 0x{b:02x}")
        finally:
            self._done()

    def read(self, addr: int, length: int, head: int | None = None, block: int = 64) -> bytes:
        _check_range(addr, length)
        try:
            if head is None:
                body = f"R{addr:04d}{length:04d}"
            else:
                body = f"L{addr:04d}{length:04d}{head}{'0' if block == 64 else '1'}"
            self._command(body)
            self._send(bytes([STX]))
            payload = self._read_exact(length + 1)
            data, got = payload[:-1], payload[-1]
            # read-response BCC = XOR(data), no STX (manual + bench-confirmed 27 Nov 2026)
            if got != bcc(data):
                raise BisError("8")
            return data
        finally:
            self._done()

    def write(self, addr: int, data: bytes, head: int | None = None, block: int = 64):
        _check_range(addr, len(data))
        try:
            if head is None:
                body = f"W{addr:04d}{len(data):04d}"
            else:
                body = f"P{addr:04d}{len(data):04d}{head}{'0' if block == 64 else '1'}"
            self._command(body)
            block_bytes = bytes([STX]) + data
            # manual example: write-data BCC covers STX + data
            self._send(block_bytes + bytes([bcc(block_bytes)]))
            self._expect_ack(timeout=60)
        finally:
            self._done()

    def find(self) -> TagHit | None:
        """H? (check once). Returns head + first 4 bytes, or None if no tag.

        H! (wait until a tag appears) is deliberately not offered: bench-tested
        27 Nov 2026, if the host stops listening while H! is pending, the unit
        stops answering every command, Q included, until its 24 V is cycled.
        """
        try:
            self._command("H?")
            resp = self._read_exact(7)  # 'H' head D1..D4 BCC, or 'H?0000' BCC
            if resp[:1] != b"H" or bcc(resp[:-1]) != resp[-1]:
                raise RuntimeError(f"bad find response {resp!r}")
            if resp[1:2] == b"?":
                return None
            return TagHit(head=int(chr(resp[1])), first4=resp[2:6])
        finally:
            self._done()

    def wait_for_tag(self, timeout: float | None = None, interval: float = 1.0) -> TagHit | None:
        """Ask H? every `interval` seconds until a tag appears or `timeout` passes.

        Each H? is answered at once, so stopping at any point (Ctrl+C, timeout,
        crash) never leaves the unit with a pending command.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            hit = self.find()
            if hit is not None:
                return hit
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(interval)

    def status(self) -> str:
        try:
            self._send_telegram("S")
            resp = self._read_exact(3)  # 'S' <state> BCC
            if resp[:1] != b"S" or bcc(resp[:-1]) != resp[-1]:
                raise RuntimeError(f"bad status response {resp!r}")
            names = {" ": "idle", "_": "idle", "R": "reading", "W": "writing", "L": "reading (L)",
                     "P": "writing (P)", "H": "head select / find"}
            return names.get(chr(resp[1]), chr(resp[1]))
        finally:
            self._done()

    def quit(self):
        try:
            self._send_telegram("Q")
            resp = self._read_exact(2)  # 'Q' BCC
            if resp != b"Q" + bytes([bcc(b"Q")]):
                raise RuntimeError(f"bad reset response {resp!r}")
            time.sleep(1.6)  # manual: wait >= 1600 ms after Quit
        finally:
            self._done()


def _check_range(addr: int, length: int):
    if not (0 <= addr <= 8191 and 1 <= length <= 8192 and addr + length <= 8192):
        raise ValueError("address 0-8191, length 1-8192, address+length within tag capacity")


def tag_events(dev: BisC600, addr: int, length: int, head: int | None, block: int,
               on_arrival=None):
    """Yield (head, data) once per tag arrival, then (None, None) when it leaves.

    Waits with H? polling (see BisC600.find) so stopping never leaves the unit stuck.
    `on_arrival(head)` is called when a tag is seen, before the (possibly slow) read.
    Transient errors (no tag, tag pulled mid-read) just restart the wait.
    """
    while True:
        try:
            hit = dev.wait_for_tag()
            use_head = head or hit.head
            if on_arrival:
                on_arrival(use_head)
            data = dev.read(addr, length, use_head, block)
            yield use_head, data
            while dev.find() is not None:
                time.sleep(1.0)
            yield None, None
        except BisError as e:
            if e.code == "3":
                print("tag removed before the read finished - not recorded", file=sys.stderr)
            elif e.code != "1":  # no tag: just wait again
                print(e, file=sys.stderr)
            time.sleep(1.0)


def decode_sfc(data: bytes) -> str | None:
    """Tag bytes -> SFC string. ASCII with trailing NUL/0xFF/space padding removed.

    Falls back to hex if the bytes aren't printable ASCII; None if the tag is blank.
    """
    trimmed = data.rstrip(b"\x00\xff ")
    if not trimmed:
        return None
    if all(32 <= c < 127 for c in trimmed):
        return trimmed.decode("ascii")
    return "HEX:" + trimmed.hex().upper()


# ---- tag record layout (from sample dumps of BIS C-122-11 tags, 27 Nov 2026) --
# 0-15   TagFixID    ASCII, NUL padded         e.g. "139", "332"
# 16-36  TagPartNo   ASCII, space/NUL padded   e.g. "LV34900"
# 37-49  TagSFC      ASCII, NUL padded         e.g. "AB593236"
# 50     0x01        unknown
# 52-59  "00000000"  unknown
# 60     0x01        unknown
# Only bytes 0-63 carry data, so `--format tag` reads 64 bytes (one page, ~0.5 s)
# instead of the whole 2 KB tag (~10 s). Field end offsets are inferred from three
# samples; confirm with whoever writes the tags.
TAG_FIELDS = {
    "TagFixID": (0, 16),
    "TagPartNo": (16, 37),
    "TagSFC": (37, 50),
}
TAG_READ_LEN = 64


def decode_tag(data: bytes) -> dict[str, str]:
    """Tag bytes -> {TagFixID, TagPartNo, TagSFC}.

    Each field ends at its first 0x00 or 0xFF byte: 0x00 is the padding seen on
    written tags, 0xFF is what never-written tag memory reads as. So a blank tag
    (zeros or FF) gives empty values rather than garbage.
    """
    out = {}
    for name, (start, end) in TAG_FIELDS.items():
        raw = data[start:end]
        cut = next((i for i, c in enumerate(raw) if c in (0x00, 0xFF)), len(raw))
        out[name] = raw[:cut].decode("ascii", errors="replace").strip()
    return out


def format_tag(fields: dict[str, str]) -> str:
    nl = "\r\n" if sys.platform == "win32" else "\n"
    return "".join(f"{k}={v}{nl}" for k, v in fields.items())


class OutputBusy(OSError):
    """The output file couldn't be written (e.g. another program has it locked)."""


def overwrite_file(path: str, text: str, attempts: int = 5, wait: float = 0.2):
    """Replace the file's whole contents (never append).

    Written to a temp file then swapped in, so anything reading the file never
    sees it half-written. Creates the folder if needed. If the swap is refused
    (Windows: another program has the file open), falls back to overwriting in
    place, retrying a few times. Raises OutputBusy if it still can't, and never
    leaves the temp file behind.
    """
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="ascii", errors="replace", newline="") as fh:
            fh.write(text)
        last = None
        for i in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:
                last = e
            try:
                with open(path, "w", encoding="ascii", errors="replace", newline="") as fh:
                    fh.write(text)
                return
            except OSError as e:
                last = e
            if i < attempts - 1:
                time.sleep(wait)
        raise OutputBusy(f"could not write {path}: {last}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def tag_text(data: bytes) -> str:
    """Tag bytes -> ASCII text: each run of printable characters, separated by one space.

    Non-text bytes (00 and FF filler, anything outside 0x20-0x7E) are dropped, so
    the result never contains tabs or line breaks and fits on one log line.
    """
    runs, cur = [], bytearray()
    for c in data:
        if 32 <= c < 127:
            cur.append(c)
        elif cur:
            runs.append(cur.decode("ascii")); cur = bytearray()
    if cur:
        runs.append(cur.decode("ascii"))
    return " ".join(r.strip() for r in runs if r.strip())


def append_line(path: str, line: str):
    """Append one line and close the file at once, so nothing is lost if the program stops.

    Creates the file's folder (e.g. C:\\balluff) if it doesn't exist yet.
    """
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\r\n" if sys.platform == "win32" else line + "\n")


def show(data: bytes):
    print("hex  :", data.hex(" "))
    print("ascii:", "".join(chr(c) if 32 <= c < 127 else "." for c in data))


def selftest():
    """Worked examples from the manual - all must match."""
    cases = {
        "L0013012820": 0x47, "L0050001020": 0x4A, "P0500000520": 0x52,
        "R00500010": 0x56, "W05000005": 0x57, "H1": 0x79, "H?": 0x77,
        "B21": 0x41, "BAO": 0x4C, "Q": 0x51, "S": 0x53,
    }
    ok = all(bcc(k.encode()) == v for k, v in cases.items())
    ok &= bcc(bytes([STX]) + b"12345") == 0x33      # write data block
    ok &= bcc(b"1234567890") == 0x01                # read response block
    ok &= bcc(b"H29876") == 0x7A                    # find response
    print("BCC selftest:", "PASS" if ok else "FAIL")
    return ok


def main():
    p = argparse.ArgumentParser(description="Balluff BIS C-600-007 RS232 client")
    p.add_argument("--port", default="COM3" if sys.platform == "win32" else "/dev/ttyUSB0",
                   help="e.g. COM3 on Windows, /dev/ttyUSB0 on Linux (run 'ports' to list)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("-v", "--verbose", action="store_true", help="print raw bytes")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    sub.add_parser("ports", help="list serial ports on this PC")
    sub.add_parser("status")
    sub.add_parser("reset")
    h = sub.add_parser("head"); h.add_argument("which", choices=["1", "2", "T"])
    f = sub.add_parser("find")
    f.add_argument("--once", action="store_true", help="check once instead of waiting")
    f.add_argument("--timeout", type=float, default=60, help="seconds to wait for a tag (default 60)")
    r = sub.add_parser("read")
    r.add_argument("addr", type=int); r.add_argument("length", type=int)
    w = sub.add_parser("write")
    w.add_argument("addr", type=int); w.add_argument("data"); w.add_argument("--hex", action="store_true")
    wt = sub.add_parser("watch"); wt.add_argument("--length", type=int, default=8)
    sf = sub.add_parser("sfc", help="write each tag read to a text file")
    sf.add_argument("--file", default=DEFAULT_LOG,
                    help=f"output file; its folder is created if needed (default {DEFAULT_LOG}). "
                         "hex/sfc append one line per read; tag overwrites the file each read")
    sf.add_argument("--addr", type=int, default=0, help="tag address to start reading (default 0)")
    sf.add_argument("--length", type=int, default=None,
                    help=f"bytes to read (default {TAG_READ_LEN} for --format tag, "
                         "2048 = whole BIS C-122-11 tag (~10 s) otherwise)")
    sf.add_argument("--format", choices=["ascii", "hex", "sfc", "tag"], default="ascii",
                    help="ascii: append the text on the tag, filler dropped (default). "
                         "hex: append every byte as hex. sfc: append one ASCII SFC string from --addr. "
                         "tag: overwrite the file with TagFixID=/TagPartNo=/TagSFC= lines (station)")
    dl = sub.add_parser("decode-log", help="decode a saved hex log (date time<TAB>hex) to Tag... lines")
    dl.add_argument("file")
    dl.add_argument("--out", help="also overwrite this file with the last record decoded")
    for sp in (r, w, wt, sf):
        sp.add_argument("--head", type=int, choices=[1, 2])
        sp.add_argument("--block", type=int, choices=[32, 64], default=64,
                        help="tag page size: 32 for BIS C-1xx-02..05, 64 for -10/-11/-30/-32")
    a = p.parse_args()

    if a.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    if a.cmd == "decode-log":
        text = None
        with open(a.file, encoding="ascii", errors="replace") as fh:
            for line in fh:
                hexpart = line.strip().split("\t")[-1]
                if not hexpart:
                    continue
                try:
                    data = bytes.fromhex(hexpart)
                except ValueError:
                    print(f"skipped (not a hex log line): {line.strip()[:60]}", file=sys.stderr)
                    continue
                text = format_tag(decode_tag(data))
                print(text, end="")
        if a.out and text is not None:
            overwrite_file(a.out, text)
        return
    if a.cmd == "ports":
        if serial is None:
            sys.exit("pyserial is not installed: pip install pyserial")
        from serial.tools import list_ports
        found = list(list_ports.comports())
        for pt in found:
            print(f"{pt.device:12} {pt.description}")
        if not found:
            print("no serial ports found - is the USB-RS232 adapter plugged in and its driver installed?")
        return

    dev = BisC600(a.port, a.baud, a.verbose)
    try:
        if a.cmd == "status":
            print("status:", dev.status())
        elif a.cmd == "reset":
            dev.quit(); print("reset done")
        elif a.cmd == "head":
            r_ = dev.select_head(a.which)
            print("head selected" + (f", tag on head {r_}" if r_ else ""))
        elif a.cmd == "find":
            hit = dev.find() if a.once else dev.wait_for_tag(a.timeout)
            if hit:
                print(f"tag on head {hit.head}"); show(hit.first4)
            else:
                print("no tag")
        elif a.cmd == "read":
            show(dev.read(a.addr, a.length, a.head, a.block))
        elif a.cmd == "write":
            data = bytes.fromhex(a.data) if a.hex else a.data.encode("latin-1")
            dev.write(a.addr, data, a.head, a.block); print(f"wrote {len(data)} bytes")
        elif a.cmd == "watch":
            print("waiting for tags (Ctrl+C to stop)...")
            for head, data in tag_events(dev, 0, a.length, a.head, a.block):
                if data is None:
                    print(f"{time.strftime('%H:%M:%S')}  tag removed")
                else:
                    print(f"{time.strftime('%H:%M:%S')}  head {head}")
                    show(data)
        elif a.cmd == "sfc":
            length = a.length or (TAG_READ_LEN if a.format == "tag" else 2048)
            verb = "writing each tag to" if a.format == "tag" else "logging tag reads to"
            print(f"{verb} {os.path.abspath(a.file)} (Ctrl+C to stop)...")
            arrived = lambda h: print(f"{time.strftime('%H:%M:%S')}  tag on head {h}: "
                                      "reading, hold the part on the head...", flush=True)
            for head, data in tag_events(dev, a.addr, length, a.head, a.block, arrived):
                if data is None:
                    continue
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                if a.format == "tag":
                    fields = decode_tag(data)
                    shown = "  ".join(f"{k}={v}" for k, v in fields.items())
                    try:
                        overwrite_file(a.file, format_tag(fields))
                    except OSError as e:  # file locked by another program: skip this read, keep running
                        print(f"{stamp}  {shown}  ** NOT SAVED: {e}", file=sys.stderr)
                        continue
                    print(f"{stamp}  {shown}")
                    continue
                if a.format == "hex":
                    value = data.hex().upper()
                    shown = f"{len(data)} bytes logged"
                elif a.format == "ascii":
                    value = tag_text(data)
                    shown = value or "(blank tag)"
                else:
                    value = decode_sfc(data) or ""
                    shown = value or "(blank tag)"
                # A blank tag is still a valid read: log it with an empty value.
                try:
                    append_line(a.file, f"{stamp}\t{value}")
                except OSError as e:
                    print(f"{stamp}  {shown}  ** NOT SAVED: {e}", file=sys.stderr)
                    continue
                print(f"{stamp}  {shown}")
    except BisError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()


if __name__ == "__main__":
    main()
