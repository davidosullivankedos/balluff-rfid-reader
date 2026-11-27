"""Tests for bisc600 against a simulated reader (no hardware needed).

Run from the repo root:  python -m unittest
"""
import os
import tempfile
import unittest

import bisc600 as b


class FakeSerial:
    """Stands in for serial.Serial: replays canned replies and records what was sent."""

    def __init__(self, replies: bytes):
        self.rx = bytearray(replies)
        self.tx = bytearray()

    def write(self, data):
        self.tx += data

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def close(self):
        pass


def make_dev(replies: bytes) -> b.BisC600:
    dev = b.BisC600.__new__(b.BisC600)  # skip __init__, which opens a real port
    dev.verbose = False
    dev.timeout = 0.5
    dev._last = 0.0
    dev.ser = FakeSerial(replies)
    return dev


def bc(data: bytes) -> bytes:
    return bytes([b.bcc(data)])


ACK0 = b"\x06" + b"0"


class BccTests(unittest.TestCase):
    def test_manual_worked_examples(self):
        self.assertTrue(b.selftest())


class StatusAndResetTests(unittest.TestCase):
    def test_status_idle(self):
        self.assertEqual(make_dev(b"S_" + bc(b"S_")).status(), "idle")

    def test_status_idle_is_space_on_real_unit(self):
        # bench trace 27 Nov 2026: >> 53 53  << 53 20 73
        self.assertEqual(make_dev(bytes.fromhex("532073")).status(), "idle")

    def test_status_bad_bcc(self):
        with self.assertRaises(RuntimeError):
            make_dev(b"S_X").status()

    def test_quit_sends_q_and_checks_reply(self):
        dev = make_dev(b"Q" + bc(b"Q"))
        dev.quit()
        self.assertEqual(bytes(dev.ser.tx), b"Q" + bc(b"Q"))


class SelectHeadTests(unittest.TestCase):
    def test_head1_with_ack_byte(self):
        self.assertEqual(make_dev(ACK0).select_head("1"), 0)

    def test_bare_zero_without_ack_byte_rejected(self):
        # bench-confirmed: the unit always sends 0x06 before '0'
        with self.assertRaises(RuntimeError):
            make_dev(b"0").select_head("1")

    def test_t_head_replaces_zero(self):
        self.assertEqual(make_dev(b"\x062").select_head("T"), 2)

    def test_t_head_follows_zero(self):
        self.assertEqual(make_dev(ACK0 + b"1").select_head("T"), 1)

    def test_t_no_tag(self):
        self.assertEqual(make_dev(ACK0).select_head("T"), 0)

    def test_nak(self):
        with self.assertRaises(b.BisError) as ctx:
            make_dev(b"\x15" + b"9").select_head("1")
        self.assertEqual(ctx.exception.code, "9")


class ReadTests(unittest.TestCase):
    def test_read_real_unit_trace(self):
        # bench trace 27 Nov 2026, BIS C-122-11 on head 1:
        # >> L0000001610J  << 06 30  >> 02  << 48 00*15 48
        data = bytes.fromhex("48") + bytes(15)
        dev = make_dev(ACK0 + data + bc(data))
        self.assertEqual(dev.read(0, 16, head=1, block=64), data)
        self.assertEqual(bytes(dev.ser.tx), b"L0000001610J\x02")

    def test_read_rejects_bcc_including_stx(self):
        data = b"1234567890"
        with self.assertRaises(b.BisError) as ctx:
            make_dev(ACK0 + data + bc(b"\x02" + data)).read(0, 10, head=1)
        self.assertEqual(ctx.exception.code, "8")


class FindTests(unittest.TestCase):
    def test_find_real_unit_trace(self):
        # bench trace 27 Nov 2026: >> 48 3f 77  << 06 30  << 48 31 48 00 00 00 31
        dev = make_dev(bytes.fromhex("0630" "48314800000031"))
        hit = dev.find()
        self.assertEqual((hit.head, hit.first4), (1, bytes.fromhex("48000000")))
        self.assertEqual(bytes(dev.ser.tx), b"H?w")

    def test_find_no_tag(self):
        self.assertIsNone(make_dev(ACK0 + b"H?0000" + bc(b"H?0000")).find())

    def test_wait_for_tag_polls_until_tag(self):
        none = ACK0 + b"H?0000" + bc(b"H?0000")
        tag = ACK0 + b"H21234" + bc(b"H21234")
        dev = make_dev(none + none + tag)
        hit = dev.wait_for_tag(interval=0)
        self.assertEqual((hit.head, hit.first4), (2, b"1234"))
        self.assertEqual(bytes(dev.ser.tx), b"H?w" * 3)  # never sends H!

    def test_wait_for_tag_times_out(self):
        none = ACK0 + b"H?0000" + bc(b"H?0000")
        self.assertIsNone(make_dev(none * 3).wait_for_tag(timeout=0, interval=0))


class SfcTests(unittest.TestCase):
    def test_ascii_with_nul_padding(self):
        self.assertEqual(b.decode_sfc(b"SFC-000123\x00\x00\x00"), "SFC-000123")

    def test_ff_and_space_padding(self):
        self.assertEqual(b.decode_sfc(b"ABC123  \xff\xff"), "ABC123")

    def test_blank_tag(self):
        self.assertIsNone(b.decode_sfc(bytes(32)))
        self.assertIsNone(b.decode_sfc(b"\xff" * 32))

    def test_non_ascii_falls_back_to_hex(self):
        self.assertEqual(b.decode_sfc(b"\x01\x02\xab"), "HEX:0102AB")

    def test_tag_text_real_test_tag(self):
        # layout of the bench test tag: SFC at 0, "harry" at 37, CE at 256, FF filler
        data = bytearray(b"\xff" * 2048)
        data[0:37] = b"TEST-SFC-0001" + bytes(24)
        data[37:42] = b"harry"
        data[42:256] = bytes(214)
        data[256] = 0xCE
        self.assertEqual(b.tag_text(bytes(data)), "TEST-SFC-0001 harry")

    def test_tag_text_blank(self):
        self.assertEqual(b.tag_text(b"\xff" * 64 + bytes(64)), "")

    def test_tag_text_no_tabs_or_newlines(self):
        self.assertEqual(b.tag_text(b"AB\tCD\r\nEF"), "AB CD EF")

    def test_append_line_creates_missing_folder(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "balluff", "sfc_log.txt")
            b.append_line(path, "x")
            self.assertTrue(os.path.isfile(path))

    def test_append_line_one_per_call(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.txt")
            b.append_line(path, "2026-11-27 09:00:00\tA1")
            b.append_line(path, "2026-11-27 09:00:05\tB2")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read().splitlines(),
                                 ["2026-11-27 09:00:00\tA1", "2026-11-27 09:00:05\tB2"])


# First 64 bytes of real tags (David's sample dumps, 27 Nov 2026)
TAG_139 = bytes.fromhex(
    "31333900000000000000000000000000" "4C563334393030202020202020202020"
    "20202020004142353933323336000000" "00000100303030303030303001000000")
TAG_332 = bytes.fromhex(
    "33333200000000000000000000000000" "4C563334393030202020202020202020"
    "20202020004142353933313931000000" "00000100303030303030303001000000")


class TagFormatTests(unittest.TestCase):
    def test_decode_sample_139(self):
        self.assertEqual(b.decode_tag(TAG_139),
                         {"TagFixID": "139", "TagPartNo": "LV34900", "TagSFC": "AB593236"})

    def test_decode_sample_332_ignores_ff_beyond_64(self):
        full = TAG_332 + b"\xff" * (2048 - 64)
        self.assertEqual(b.decode_tag(full),
                         {"TagFixID": "332", "TagPartNo": "LV34900", "TagSFC": "AB593191"})

    def test_format_order_and_keys(self):
        lines = b.format_tag(b.decode_tag(TAG_139)).splitlines()
        self.assertEqual(lines, ["TagFixID=139", "TagPartNo=LV34900", "TagSFC=AB593236"])

    def test_blank_tag_gives_empty_values(self):
        self.assertEqual(b.decode_tag(bytes(64)),
                         {"TagFixID": "", "TagPartNo": "", "TagSFC": ""})

    def test_overwrite_replaces_not_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "balluff", "sfc_log.txt")  # folder doesn't exist yet
            b.overwrite_file(path, b.format_tag(b.decode_tag(TAG_139)))
            b.overwrite_file(path, b.format_tag(b.decode_tag(TAG_332)))
            with open(path, encoding="ascii") as fh:
                self.assertEqual(fh.read().splitlines(),
                                 ["TagFixID=332", "TagPartNo=LV34900", "TagSFC=AB593191"])
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_never_written_tag_ff_gives_empty_values(self):
        self.assertEqual(b.decode_tag(b"\xff" * 64),
                         {"TagFixID": "", "TagPartNo": "", "TagSFC": ""})

    def test_ff_padding_ends_field(self):
        data = bytearray(b"\xff" * 64)
        data[0:3] = b"139"
        data[37:45] = b"AB593236"
        self.assertEqual(b.decode_tag(bytes(data)),
                         {"TagFixID": "139", "TagPartNo": "", "TagSFC": "AB593236"})

    def test_overwrite_locked_file_raises_busy_and_cleans_up(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sfc_log.txt")
            real_open = open

            def locked_open(f, mode="r", *a, **k):
                if f == os.path.abspath(path) and "w" in mode:
                    raise PermissionError("in use by another program")
                return real_open(f, mode, *a, **k)

            with mock.patch("os.replace", side_effect=PermissionError("in use")), \
                 mock.patch("builtins.open", locked_open):
                with self.assertRaises(b.OutputBusy):
                    b.overwrite_file(path, "x", attempts=2, wait=0)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_overwrite_falls_back_when_swap_refused(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sfc_log.txt")
            with mock.patch("os.replace", side_effect=PermissionError("in use")):
                b.overwrite_file(path, "TagSFC=AB1\n", wait=0)
            with open(path) as fh:
                self.assertEqual(fh.read(), "TagSFC=AB1\n")
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_tag_read_is_one_page(self):
        self.assertEqual(b.TAG_READ_LEN, 64)


if __name__ == "__main__":
    unittest.main()
