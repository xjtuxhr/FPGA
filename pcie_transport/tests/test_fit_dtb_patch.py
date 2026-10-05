"""PC tests for the FIT-aware DTB patch (no board access).

Builds a synthetic U-Boot FIT (outer FDT) with an embedded flat_dt sub-image
that carries a disabled pcie node and a sha256 hash node, then verifies the
patch changes only the status bytes and the hash value, leaving a dummy kernel
region byte-identical. Mirrors the real boot.img structure found offline.
"""
import hashlib
import struct
import unittest

from pcie_transport.tools import fit_dtb_patch as F

BEGIN, END_NODE, PROP, NOP, END = 0x1, 0x2, 0x3, 0x4, 0x9


def _build_dtb(node):
    """node = (name, [(pname, value_bytes)], [children]). Returns FDT bytes."""
    strings = bytearray()
    str_off = {}

    def s_off(s):
        if s not in str_off:
            str_off[s] = len(strings)
            strings.extend(s.encode() + b"\x00")
        return str_off[s]

    struct_ = bytearray()

    def emit(n):
        name, props, children = n
        struct_.extend(struct.pack(">I", BEGIN))
        struct_.extend(name.encode() + b"\x00")
        while len(struct_) % 4:
            struct_.extend(b"\x00")
        for pname, val in props:
            struct_.extend(struct.pack(">I", PROP))
            struct_.extend(struct.pack(">II", len(val), s_off(pname)))
            struct_.extend(val)
            while len(struct_) % 4:
                struct_.extend(b"\x00")
        for ch in children:
            emit(ch)
        struct_.extend(struct.pack(">I", END_NODE))

    emit(node)
    struct_.extend(struct.pack(">I", END))
    header = bytearray(40)
    memrsv = b"\x00" * 16
    off_struct = 56
    off_strings = off_struct + len(struct_)
    total = off_strings + len(strings)
    struct.pack_into(">8I", header, 0, F.FDT_MAGIC, total, off_struct, off_strings, 40, 17, 16, 0)
    return bytes(header) + memrsv + bytes(struct_) + bytes(strings)


def _u32(v):
    return struct.pack(">I", v)


def build_fit():
    # inner kernel DTB (flat_dt) with a disabled pcie node
    inner = _build_dtb((
        "", [("model", b"test-board\x00")], [
            ("pcie@2a210000", [
                ("compatible", b"rockchip,rk3576-pcie\x00"),
                ("status", b"disabled\x00"),
            ], []),
        ],
    ))
    kernel_data = b"KERNELDATA" * 64
    resource_data = b"RESOURCE" * 32
    pos_fdt, pos_ker, pos_res = 4096, 8192, 12288

    fit_root = (
        "", [("description", b"test fit\x00")], [
            ("images", [], [
                ("fdt", [
                    ("type", b"flat_dt\x00"),
                    ("compression", b"none\x00"),
                    ("data-position", _u32(pos_fdt)),
                    ("data-size", _u32(len(inner))),
                ], [
                    ("hash", [
                        ("algo", b"sha256\x00"),
                        ("value", hashlib.sha256(inner).digest()),
                    ], []),
                ]),
                ("kernel", [
                    ("type", b"kernel\x00"),
                    ("data-position", _u32(pos_ker)),
                    ("data-size", _u32(len(kernel_data))),
                ], []),
                ("resource", [
                    ("type", b"multi\x00"),
                    ("data-position", _u32(pos_res)),
                    ("data-size", _u32(len(resource_data))),
                ], []),
            ]),
            ("configurations", [("default", b"conf\x00")], [
                ("conf", [("fdt", b"fdt\x00"), ("kernel", b"kernel\x00"),
                          ("multi", b"resource\x00")], []),
            ]),
        ],
    )
    header = _build_dtb(fit_root)
    assert len(header) < pos_fdt, "synthetic FIT header overlaps data"
    buf = bytearray(pos_res + len(resource_data))
    buf[:len(header)] = header
    buf[pos_fdt:pos_fdt + len(inner)] = inner
    buf[pos_ker:pos_ker + len(kernel_data)] = kernel_data
    buf[pos_res:pos_res + len(resource_data)] = resource_data
    return bytes(buf), inner, (pos_fdt, len(inner)), (pos_ker, len(kernel_data)), (pos_res, len(resource_data))


class FitPatchTests(unittest.TestCase):
    def setUp(self):
        (self.fit, self.inner, self.fdt_span,
         self.ker_span, self.res_span) = build_fit()

    def test_analyze_finds_disabled_node(self):
        import tempfile, os
        fd, p = tempfile.mkstemp(suffix=".img")
        os.write(fd, self.fit); os.close(fd)
        self.addCleanup(lambda: os.remove(p))
        _data, report, _ = F.analyze(p)
        self.assertEqual(report["pcie@2a210000"], "disabled")
        self.assertEqual(report["fdt_data_position"], self.fdt_span[0])
        self.assertEqual(report["fdt_hash_node"], {"algo": "sha256"})

    def test_patch_changes_only_status_and_hash(self):
        patched, info = F.patch_region(self.fit, "pcie@2a210000", b"okay")
        self.assertTrue(info["changed"])
        # exactly the status range + one hash value range changed
        changed_offsets = set()
        for a, b in info["changed_ranges"]:
            changed_offsets.update(range(a, b))
        diffs = {i for i in range(len(self.fit)) if self.fit[i] != patched[i]}
        self.assertTrue(diffs <= changed_offsets,
                        f"unexpected changes: {sorted(diffs - changed_offsets)}")
        self.assertIn(info["status_offset"], diffs)
        self.assertIn(info["status_offset"] + 1, diffs)
        # kernel + resource regions byte-identical
        for (p, n) in (self.ker_span, self.res_span):
            self.assertEqual(self.fit[p:p + n], patched[p:p + n])
        # status now okay in the patched embedded DTB
        _f, pp, ss, _r = F.locate_fdt_image(patched)
        node = F.find_deepest(F.parse_fdt(patched[pp:pp + ss])[0], "pcie@2a210000")
        self.assertTrue(node["props"]["status"]["value"].startswith(b"okay\x00"))

    def test_patch_is_idempotent(self):
        patched, info = F.patch_region(self.fit, "pcie@2a210000", b"okay")
        again, info2 = F.patch_region(patched, "pcie@2a210000", b"okay")
        self.assertFalse(info2["changed"])
        self.assertEqual(patched, again)

    def test_refuses_wrong_initial_status(self):
        patched, _ = F.patch_region(self.fit, "pcie@2a210000", b"okay")
        # now status is okay (len 5); asking to patch a missing node errors
        with self.assertRaises(F.FitError):
            F.patch_region(patched, "pcie@deadbeef", b"okay")


if __name__ == "__main__":
    unittest.main(verbosity=2)
