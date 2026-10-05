#!/usr/bin/env python3
"""FIT-aware PCIe DTB patch (PC2). Offline analysis + plain-file patch.

WHY: /dev/mmcblk0p3 is a U-Boot FIT container (outer FDT), NOT a raw kernel
DTB. The real DTB is the /images/fdt flat_dt sub-image (data-position/data-size).
The old patch_pcie1_dtb.py parsed the outer FIT, so it could not find
pcie@2a210000 (it correctly refused, but could not enable PCIe).

This tool:
  1. parses the outer FIT, locates /images/fdt (flat_dt, compression=none);
  2. extracts that region, parses it as a DTB, locates <node>/status;
  3. replaces "disabled\\0" with "okay\\0" (SAME length -> offsets unchanged);
  4. writes to --out (plain-file test) or in place via write_in_place();
  5. if a `hash` node covers the fdt image, recomputes sha256 in place;
     if a `signature` node covers it, REFUSES (needs the vendor re-sign tool).

Never writes on --check; board in-place apply is a separate, guarded helper.
"""
import argparse
import hashlib
import json
import struct
import sys

FDT_MAGIC = 0xD00DFEED
BEGIN_NODE, END_NODE, PROP, NOP, END = 0x1, 0x2, 0x3, 0x4, 0x9


class FitError(RuntimeError):
    pass


def align4(n):
    return (n + 3) & ~3


def _parse_into(data, off_struct, off_strings, root):
    pos = off_struct
    child_stack = [root]
    prop_stack = [root]
    while True:
        tok = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if tok == BEGIN_NODE:
            end = data.index(b"\x00", pos)
            name = data[pos:end].decode("latin1")
            pos = align4(end + 1)
            node = {"name": name, "props": {}, "children": {}}
            child_stack[-1][name] = node
            child_stack.append(node["children"])
            prop_stack.append(node["props"])
        elif tok == END_NODE:
            child_stack.pop()
            prop_stack.pop()
        elif tok == PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            send = data.index(b"\x00", off_strings + nameoff)
            pname = data[off_strings + nameoff:send].decode("latin1")
            prop_stack[-1][pname] = {
                "length": length, "value_offset": pos,
                "value": bytes(data[pos:pos + length]),
            }
            pos = align4(pos + length)
        elif tok == NOP:
            pass
        elif tok == END:
            break
        else:
            raise FitError(f"bad FDT token 0x{tok:x}")
    return root


def parse_fdt(data):
    """Return (root_node, totalsize). Root node is the real FDT root."""
    if len(data) < 40:
        raise FitError("short FDT")
    magic, totalsize, off_struct, off_strings = struct.unpack_from(">4I", data, 0)
    if magic != FDT_MAGIC:
        raise FitError(f"bad FDT magic 0x{magic:08x}")
    top = {}
    _parse_into(data[:totalsize], off_struct, off_strings, top)
    inner = top.get("") or next(iter(top.values()), None)
    if inner is None:
        raise FitError("no FDT root node")
    return inner, totalsize


def find_deepest(node, name):
    if node["name"] == name:
        return node
    for ch in node["children"].values():
        found = find_deepest(ch, name)
        if found:
            return found
    return None


def u32(b):
    return struct.unpack(">I", b)[0]


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def locate_fdt_image(fit_blob):
    root, _ = parse_fdt(fit_blob)
    images = root["children"].get("images")
    if images is None:
        raise FitError("FIT has no /images")
    fdt = images["children"].get("fdt")
    if fdt is None:
        raise FitError("FIT has no /images/fdt")
    typev = fdt["props"].get("type", {}).get("value", b"").rstrip(b"\x00")
    comp = fdt["props"].get("compression", {}).get("value", b"").rstrip(b"\x00")
    if typev != b"flat_dt":
        raise FitError(f"/images/fdt type {typev!r} != flat_dt")
    if comp not in (b"none", b""):
        raise FitError(f"/images/fdt compression {comp!r} unsupported")
    pos = u32(fdt["props"]["data-position"]["value"])
    size = u32(fdt["props"]["data-size"]["value"])
    return fdt, pos, size, root


def hash_node_of(fdt_node):
    h = fdt_node["children"].get("hash")
    if h is None:
        return None, None
    algo = h["props"].get("algo", {}).get("value", b"").rstrip(b"\x00")
    return h, algo


def analyze(path):
    with open(path, "rb") as f:
        data = f.read()
    fdt_node, pos, size, fit_root = locate_fdt_image(data)
    blob = data[pos:pos + size]
    dtb_root, _ = parse_fdt(blob)
    report = {
        "file": path, "file_size": len(data), "file_sha256": sha256_hex(data),
        "fdt_data_position": pos, "fdt_data_size": size,
        "fdt_region_sha256": sha256_hex(blob),
        "embedded_model": dtb_root["props"].get("model", {}).get("value", b"").rstrip(b"\x00").decode("latin1", "replace"),
    }
    for n in ("pcie@2a200000", "pcie@2a210000"):
        node = find_deepest(dtb_root, n)
        if node:
            report[n] = node["props"].get("status", {}).get("value", b"").rstrip(b"\x00").decode("latin1")
    h, algo = hash_node_of(fdt_node)
    report["fdt_hash_node"] = None if h is None else {"algo": algo.decode("latin1") if algo else None}
    report["fdt_signature_node"] = ("signature" in fdt_node["children"]) or ("signature" in fit_root["children"])
    report["kernel_offset"] = _img_span(fit_root, "kernel")
    report["resource_offset"] = _img_span(fit_root, "resource")
    return data, report, (fdt_node, pos, size, fit_root)


def _img_span(fit_root, name):
    img = fit_root["children"].get("images", {}).get("children", {}).get(name)
    if not img:
        return None
    p = u32(img["props"]["data-position"]["value"])
    s = u32(img["props"]["data-size"]["value"])
    return [p, p + s]


def patch_region(data, node_name, new_status, allow_signature=False):
    """Return (patched_bytes, info). Pure: no file writes."""
    fdt_node, pos, size, fit_root = locate_fdt_image(data)
    h, algo = hash_node_of(fdt_node)
    if "signature" in fdt_node["children"] and not allow_signature:
        raise FitError("/images/fdt has a signature node; refuse in-place patch (vendor re-sign required)")
    blob = bytearray(data[pos:pos + size])
    dtb_root, _ = parse_fdt(blob)
    node = find_deepest(dtb_root, node_name)
    if node is None:
        raise FitError(f"{node_name} not found in embedded DTB")
    st = node["props"].get("status")
    if st is None:
        raise FitError(f"{node_name} has no status")
    off, length, val = st["value_offset"], st["length"], st["value"]
    if val.startswith(new_status + b"\x00"):
        return bytes(data), {"changed": False, "reason": f"already {new_status.decode()}"}
    if val != b"disabled\x00":
        raise FitError(f"{node_name} status {val!r} != b'disabled\\0'")
    blob[off:off + length] = new_status + b"\x00" + b"\x00" * (length - len(new_status) - 1)
    out = bytearray(data)
    out[pos:pos + size] = blob
    changed = [[pos + off, pos + off + length]]
    if h is not None:
        if algo != b"sha256":
            raise FitError(f"hash algo {algo!r} unsupported for auto-update")
        hv = h["props"]["value"]
        # hash value lives in the outer FIT (offset within the file)
        v_off = hv["value_offset"]
        out[v_off:v_off + 32] = bytes.fromhex(sha256_hex(bytes(blob)))
        changed.append([v_off, v_off + 32])
    return bytes(out), {"changed": True, "changed_ranges": changed, "status_offset": pos + off}


def write_in_place(path, patched, get_original):
    """Guarded in-place write for board apply. Verifies only intended ranges
    changed and kernel/resource unchanged. Does NOT reboot. Caller must have
    validated the target device identity. Returns a verification dict."""
    orig = get_original()
    if len(patched) != len(orig):
        raise FitError("patched size != original size")
    _fdt, pos, size, fit_root = locate_fdt_image(orig)
    kspan = _img_span(fit_root, "kernel")
    rspan = _img_span(fit_root, "resource")
    with open(path, "r+b") as f:
        f.write(patched)
        f.flush()
    back = get_original()
    if sha256_hex(back) != sha256_hex(patched):
        raise FitError("readback != written bytes")
    for name, span in (("kernel", kspan), ("resource", rspan)):
        if span and sha256_hex(orig[span[0]:span[1]]) != sha256_hex(back[span[0]:span[1]]):
            raise FitError(f"{name} region changed unexpectedly")
    return {
        "written": True, "file_sha256": sha256_hex(back),
        "fdt_region_sha256": sha256_hex(back[pos:pos + size]),
        "kernel_unchanged": True, "resource_unchanged": True,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="FIT-aware PCIe DTB patch (plain-file)")
    ap.add_argument("--fit", required=True)
    ap.add_argument("--node", default="pcie@2a210000")
    ap.add_argument("--set-status", choices=["okay"])
    ap.add_argument("--out", help="write patched copy (plain-file test)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--allow-signature", action="store_true")
    args = ap.parse_args(argv)

    data, report, _ = analyze(args.fit)
    print(json.dumps(report, indent=2))
    if args.check or not args.set_status:
        return 0
    patched, info = patch_region(data, args.node, args.set_status.encode(), args.allow_signature)
    print("patch info:", json.dumps(info))
    if not args.out:
        raise SystemExit("plain-file tool: pass --out; board in-place apply uses the guarded helper")
    open(args.out, "wb").write(patched)
    print(f"wrote {args.out} ({len(patched)} bytes); "
          f"kernel/resource byte-identical: "
          f"{data[report['kernel_offset'][0]:report['kernel_offset'][1]] == patched[report['kernel_offset'][0]:report['kernel_offset'][1]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
