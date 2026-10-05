#!/usr/bin/env python3
"""Patch pcie@2a210000 status disabled->okay IN PLACE on /dev/mmcblk0p3.

SUPERSEDED for the board's p3 by tools/fit_dtb_patch.py (2026-10-05 review).
/dev/mmcblk0p3 is a U-Boot FIT container, not a raw DTB; this tool walks the
OUTER FIT and therefore cannot find pcie@2a210000 (it fails closed, but cannot
enable PCIe). This file now treats its input as a plain DTB only. Use
fit_dtb_patch.py to extract/patch the embedded flat_dt image instead.

PC2 PCIe bring-up, checkpoint 2. Must be run as root (block device write).
Fails closed: real FDT structure walk (no string search), backup before
write, running-DTB cross-check, post-patch re-verification.

Usage:
  python3 patch_pcie1_dtb.py --check-only   # report status, write nothing
  python3 patch_pcie1_dtb.py                # backup + patch + verify

Safety:
  - refuses if p3 does not start with the FDT magic
  - refuses if the p3 DTB does not match the running kernel DTB
    (/sys/firmware/fdt) unless --skip-running-check is given
  - refuses unless exactly one pcie@2a210000/status property exists and is
    exactly "disabled" (len 9)
  - backup is written BEFORE any modification
"""
import hashlib
import os
import struct
import sys
import time

DTB_PART = "/dev/mmcblk0p3"
RUNNING_FDT = "/sys/firmware/fdt"
BACKUP_DIR = "/userdata"

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 0x1
FDT_END_NODE = 0x2
FDT_PROP = 0x3
FDT_NOP = 0x4
FDT_END = 0x9

TARGET_NODE = b"pcie@2a210000"


class PatchError(RuntimeError):
    pass


def align4(n):
    return (n + 3) & ~3


def parse_structure(data, off_struct):
    """Yield (kind, name_or_none, prop_dict_or_none) tokens from the structure block."""
    pos = off_struct
    while True:
        token = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = data.index(b"\x00", pos)
            name = data[pos:end]
            yield ("node", name, None)
            pos = align4(end + 1)
        elif token == FDT_END_NODE:
            yield ("end", None, None)
        elif token == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            yield ("prop", nameoff, {"length": length, "value_offset": pos})
            pos = align4(pos + length)
        elif token == FDT_NOP:
            yield ("nop", None, None)
        elif token == FDT_END:
            yield ("end_all", None, None)
            return
        else:
            raise PatchError(f"Unknown FDT token 0x{token:08X} at structure offset {pos - 4}")


def prop_name(data, off_strings, nameoff):
    end = data.index(b"\x00", off_strings + nameoff)
    return data[off_strings + nameoff:end]


def find_status_prop(data, header):
    """Return {"value_offset": ..., "length": ...} of TARGET_NODE's status prop."""
    off_struct = struct.unpack_from(">I", data, 8)[0]
    off_strings = struct.unpack_from(">I", data, 12)[0]
    depth = 0
    target_depth = 0
    node_count = 0
    found = 0
    result = None
    for kind, name, prop in parse_structure(data, off_struct):
        if kind == "node":
            depth += 1
            if name == TARGET_NODE:
                node_count += 1
                if node_count > 1:
                    raise PatchError(f"Multiple nodes named {TARGET_NODE.decode()}")
                target_depth = depth
        elif kind == "end":
            if target_depth and depth == target_depth:
                target_depth = 0
            depth -= 1
        elif kind == "prop":
            if target_depth and depth == target_depth:
                pname = prop_name(data, off_strings, name)
                if pname == b"status":
                    found += 1
                    if found > 1:
                        raise PatchError("Multiple status properties found in target node")
                    result = {
                        "value_offset": prop["value_offset"],
                        "length": prop["length"],
                    }
        elif kind == "end_all":
            break
    if found == 0:
        raise PatchError(f"No status property found in {TARGET_NODE.decode()}")
    return result


def read_dtb(path):
    with open(path, "rb") as f:
        header = f.read(40)
        if len(header) < 40:
            raise PatchError(f"{path}: short FDT header")
        magic, totalsize = struct.unpack_from(">II", header, 0)
        if magic != FDT_MAGIC:
            raise PatchError(f"{path}: bad FDT magic 0x{magic:08X} (not a DTB)")
        if totalsize < 40 or totalsize > 8 * 1024 * 1024:
            raise PatchError(f"{path}: implausible totalsize {totalsize}")
        f.seek(0)
        return bytearray(f.read(totalsize))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def patch_blob(data, prop):
    """Overwrite ONLY the value bytes; keep the property length unchanged.

    The value slot stays its original length ("disabled\0" = 9 bytes), so
    the FDT structure alignment is untouched and the parser's next-token
    position remains valid. The patched string reads as "okay" up to the
    first NUL; the leftover bytes stay zero. (Vendor scripts that also
    rewrite the length field to 5 would leave 4 stale bytes for the parser
    to consume as a bogus token.)
    """
    length = prop["length"]
    value_offset = prop["value_offset"]
    value = bytes(data[value_offset:value_offset + length])
    if value != b"disabled\x00":
        raise PatchError(f"status value is not exactly 'disabled' (len {length}): {value!r}")
    new_value = b"okay\x00" + b"\x00" * (length - 5)
    data[value_offset:value_offset + length] = new_value
    return data


def verify_blob(data, header, patched):
    prop = find_status_prop(data, header)
    length = prop["length"]
    value = bytes(data[prop["value_offset"]:prop["value_offset"] + length])
    if patched:
        if not value.startswith(b"okay\x00"):
            raise PatchError(f"post-patch verification failed: {value!r}")
    else:
        if value != b"disabled\x00":
            raise PatchError(f"unexpected initial status: {value!r}")
    return value


def main():
    check_only = "--check-only" in sys.argv
    skip_running_check = "--skip-running-check" in sys.argv
    part = DTB_PART
    if "--part" in sys.argv:
        part = sys.argv[sys.argv.index("--part") + 1]
        skip_running_check = True  # non-board path never cross-checks the running kernel
    backup_dir = BACKUP_DIR
    if "--backup-dir" in sys.argv:
        backup_dir = sys.argv[sys.argv.index("--backup-dir") + 1]
    elif "--part" in sys.argv:
        backup_dir = os.path.dirname(os.path.abspath(part)) or "."

    data = read_dtb(part)
    header = bytes(data[:40])
    prop = find_status_prop(data, header)
    length = prop["length"]
    current = bytes(data[prop["value_offset"]:prop["value_offset"] + length])
    print(f"[DTB] {TARGET_NODE.decode()} status = {current!r} (len {length}) from {part}")

    if current.startswith(b"okay\x00"):
        print("status is already okay; nothing to patch")
        return 0
    if current != b"disabled\x00":
        raise PatchError(f"unexpected initial status: {current!r}")

    if not skip_running_check:
        try:
            running = open(RUNNING_FDT, "rb").read()
        except OSError as exc:
            raise PatchError(f"cannot read {RUNNING_FDT}: {exc}")
        running = running[:struct.unpack_from(">I", running, 4)[0]] if len(running) >= 8 else running
        if sha256(bytes(data)) != sha256(running):
            raise PatchError(
                "p3 DTB differs from the running kernel DTB; this partition may not be "
                "the boot DTB. Stop and investigate before patching."
            )
        print("[cross-check] p3 DTB matches running kernel DTB")
    else:
        print("[cross-check] SKIPPED (--skip-running-check)")

    if check_only:
        print("[check-only] would patch status disabled -> okay; rerun without flags to apply")
        return 0

    backup = os.path.join(backup_dir, "p3_dtb_backup_%s.bin" % time.strftime("%Y%m%d_%H%M%S"))
    with open(backup, "wb") as f:
        f.write(data)
    print(f"[backup] {backup} ({len(data)} bytes, sha256 {sha256(bytes(data))[:16]}...)")

    patched = patch_blob(data, prop)
    verify_blob(patched, header, patched=True)
    print("[verify] in-memory patch OK: status = okay")

    with open(part, "r+b") as f:
        f.seek(0)
        f.write(patched)
    print(f"[write] patched DTB written back to {part}")
    print("Done. Reboot required. Recovery: dd if=<backup> of=/dev/mmcblk0p3 bs=1M")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PatchError as exc:
        print(f"PATCH_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
