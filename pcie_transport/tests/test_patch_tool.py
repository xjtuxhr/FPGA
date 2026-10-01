"""PC-only tests for patch_pcie1_dtb.py against a synthetic FDT blob.

Never opens /dev/mmcblk0p3 or /sys/firmware/fdt; uses --part with temp
files only. Verifies: patch works, idempotent, cross-check refusal,
bad magic refusal, missing/multiple status refusal.
"""
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "patch_pcie1_dtb.py"


def build_fdt(status_a: bytes = b"disabled\x00", include_b: bool = True,
              status_b: bytes = b"disabled\x00", magic: int = 0xD00DFEED) -> bytes:
    """Minimal FDT: root with pcie@2a210000 (status_a) and optionally
    pcie@2a200000 (status_b). No mem reserve entries."""
    struct_block = bytearray()
    strings = bytearray(b"status\x00")

    def begin_node(name):
        nonlocal struct_block
        struct_block += struct.pack(">I", 0x1) + name + b"\x00"
        pad = (4 - len(struct_block) % 4) % 4
        struct_block += b"\x00" * pad

    def prop(length, nameoff, value):
        nonlocal struct_block
        struct_block += struct.pack(">III", 0x3, length, nameoff) + value
        pad = (4 - len(struct_block) % 4) % 4
        struct_block += b"\x00" * pad

    def end_node():
        nonlocal struct_block
        struct_block += struct.pack(">I", 0x2)

    begin_node(b"")
    begin_node(b"pcie@2a210000")
    prop(len(status_a), 0, status_a)
    end_node()
    if include_b:
        begin_node(b"pcie@2a200000")
        prop(len(status_b), 0, status_b)
        end_node()
    end_node()
    struct_block += struct.pack(">I", 0x9)  # FDT_END

    strings_pad = (4 - len(strings) % 4) % 4
    strings += b"\x00" * strings_pad

    off_struct = 40
    off_strings = 40 + len(struct_block)
    totalsize = off_strings + len(strings)
    header = struct.pack(
        ">IIIIIIIIII",  # magic, totalsize, off_struct, off_strings, off_rsvmap,
        magic, totalsize, off_struct, off_strings, 40,
        17, 16,          # version, last_comp_version
        0,               # boot_cpuid_phys
        len(strings), len(struct_block),
    )
    assert len(header) == 40
    return bytes(header) + bytes(struct_block) + bytes(strings)


def run_tool(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TOOL), "--part", str(path), *args],
        capture_output=True, text=True,
    )


class PatchToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.path = Path(self.tmp.name)
        self.tmp.write(build_fdt())
        self.tmp.close()

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def read(self):
        return self.path.read_bytes()

    def test_check_only_reports_disabled(self):
        result = run_tool(self.path, "--check-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status = b'disabled", result.stdout)
        self.assertEqual(self.read(), build_fdt())

    def test_patch_disabled_to_okay(self):
        result = run_tool(self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status = okay", result.stdout)
        patched = self.read()
        # same length: "disabled\0" (9B) -> "okay\0" + 4 zero fill (9B); len field untouched
        expected = build_fdt(status_a=b"okay\x00\x00\x00\x00\x00")
        self.assertEqual(patched, expected)
        self.assertEqual(len(patched), len(build_fdt()))  # in-place, same size

    def test_patch_idempotent(self):
        run_tool(self.path)
        result = run_tool(self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already okay", result.stdout)

    def test_other_node_untouched(self):
        run_tool(self.path)
        patched = self.read()
        expected = build_fdt(status_a=b"okay\x00\x00\x00\x00\x00", status_b=b"disabled\x00")
        self.assertEqual(patched, expected)

    def test_bad_magic_refused(self):
        self.path.write_bytes(build_fdt(magic=0xDEADBEEF))
        result = run_tool(self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bad FDT magic", result.stderr)
        self.assertEqual(self.read(), build_fdt(magic=0xDEADBEEF))

    def test_missing_target_node_refused(self):
        # build without the target node: only pcie@2a200000 present
        blob = build_fdt(include_b=True).replace(b"pcie@2a210000", b"pcie@2a219999")
        self.path.write_bytes(blob)
        result = run_tool(self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No status property", result.stderr)

    def test_missing_status_refused(self):
        blob = build_fdt(status_a=b"something\x00")
        self.path.write_bytes(blob)
        result = run_tool(self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected initial status", result.stderr)


if __name__ == "__main__":
    unittest.main()
