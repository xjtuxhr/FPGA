#!/usr/bin/env python3
"""8 consecutive real-NPU U-golden frames (pos0..7) + first C2H-timeout diagnostics."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
GOLD = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_npu_v40_capture_golden"
OUT = "/home/kvdev/pcie_bringup_20261024/u_npu_golden_8frame_20261024"
START = 12500
TIMEOUT = 12.0
REG_OFFSETS = (0x5C, 0x74, 0x84, 0x90, 0x94, 0x98, 0x9C, 0xA0, 0xA4, 0xA8, 0xAC, 0xB0)

sys.path.insert(0, PKG)
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def run(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=20, check=False)
        return p.stdout.decode("utf-8", "replace")
    except Exception as exc:
        return "COMMAND FAILED %r: %s" % (cmd, exc)


def read_regs():
    out = {}
    try:
        fd = os.open("/dev/ANLOGIC-PCI0_user", os.O_RDONLY)
        try:
            for off in REG_OFFSETS:
                out["0x%02X" % off] = "0x%08X" % struct.unpack("<I", os.pread(fd, 4, off))[0]
        finally:
            os.close(fd)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def save_diagnostics(root, label, active, err, tr):
    d = os.path.join(root, "diag_%s" % label)
    os.makedirs(d, exist_ok=True)
    texts = {
        "date.txt": run(["date", "-u"]),
        "uptime.txt": run(["uptime"]),
        "uname.txt": run(["uname", "-a"]),
        "dmesg_full.txt": run(["dmesg"]),
        "dmesg_filtered.txt": run(["sh", "-c",
            "dmesg | grep -i -E 'anlogic|sgdma|pcie|c2h|h2c|timeout|abort' | tail -200"]),
        "lspci_nn.txt": run(["lspci", "-nn"]),
        "lspci_vv.txt": run(["lspci", "-vv"]),
        "lsmod.txt": run(["lsmod"]),
        "ps.txt": run(["ps", "-ef"]),
        "free.txt": run(["free", "-h"]),
        "dev.txt": run(["sh", "-c", "ls -l /dev/ANLOGIC* /dev/sgdma* 2>&1"]),
        "module_params.txt": run(["sh", "-c",
            "for f in /sys/module/anlogic_pci/parameters/*; do echo \"$f=$(cat $f)\"; done"]),
        "link.txt": run(["sh", "-c",
            "cat /sys/bus/pci/devices/0000:21:00.0/current_link_speed "
            "/sys/bus/pci/devices/0000:21:00.0/current_link_width 2>&1"]),
    }
    for name, text in texts.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)

    sysfs = os.path.join(d, "sysfs")
    os.makedirs(sysfs, exist_ok=True)
    base = "/sys/bus/pci/devices/0000:21:00.0"
    for name in ("vendor", "device", "class", "current_link_speed", "current_link_width",
                 "resource", "irq", "enable", "driver"):
        try:
            src = os.path.join(base, name)
            if os.path.isdir(src):
                continue
            dst = os.path.join(sysfs, name)
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            else:
                shutil.copyfile(src, dst)
        except Exception:
            pass

    diag = {
        "label": label,
        "failure_type": err["type"],
        "message": err["message"],
        "active": active,
        "transport_state": tr.state.value,
        "next_seq": tr.next_seq,
        "monotonic_s": time.monotonic(),
        "bar0_registers": read_regs(),
        "dmesg_filtered": texts["dmesg_filtered.txt"],
        "note": "No retry, no reset, no driver recovery was attempted after this failure.",
    }
    with open(os.path.join(d, "diagnostic.json"), "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2)
    return d


def main():
    if os.path.exists(OUT):
        raise SystemExit("refusing to overwrite existing OUT: " + OUT)
    os.makedirs(OUT)
    manifest = json.load(open(os.path.join(GOLD, "manifest.json"), encoding="utf-8"))
    rows = manifest["rows"]
    if len(rows) != 8 or [r["position"] for r in rows] != list(range(8)):
        raise SystemExit("golden manifest must contain positions 0..7")
    golden = []
    for r in rows:
        p = r["position"]
        q = read_file(os.path.join(GOLD, "pos%03d.qkv.fp16.bin" % p))
        a = read_file(os.path.join(GOLD, "pos%03d.attention.fp16.bin" % p))
        if len(q) != 1920 or len(a) != 1152:
            raise SystemExit("bad golden lengths at pos %d" % p)
        if sha(q) != r["input_sha256"] or sha(a) != r["output_sha256"]:
            raise SystemExit("golden hash mismatch at pos %d" % p)
        golden.append((q, a))

    binding = Binding.load(BINDING)
    dev = SgdmaDevice(binding)
    tr = Transport(dev, binding)
    tr.next_seq = START
    summary = {
        "real_date_utc": "2026-10-24",
        "golden_dir": GOLD,
        "golden_manifest_sha256": sha(read_file(os.path.join(GOLD, "manifest.json"))),
        "binding": BINDING,
        "start_seq": START,
        "timeout_s": TIMEOUT,
        "bit_sha256_from_B": "B5AD8F911EC270E448993D09C1BC243B4420D873870B3B18D39BD46A2958B26B",
        "status": "running",
        "rows": [],
    }
    active = None
    try:
        summary["reset_seq"] = tr.next_seq
        rt = tr.reset_cache(timeout_s=TIMEOUT)
        summary["reset_total_s"] = rt.total_s
        for pos, (qkv, expected) in enumerate(golden):
            seq = tr.next_seq
            active = {"position": pos, "seq": seq}
            with open(os.path.join(OUT, "pos%03d.request.h2c.bin" % pos), "wb") as f:
                f.write(c.pack_request(seq, 0, pos, qkv, op=c.OP_ATTENTION))
            with open(os.path.join(OUT, "pos%03d.golden.attention.bin" % pos), "wb") as f:
                f.write(expected)
            t0 = time.monotonic()
            resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, qkv, timeout_s=TIMEOUT)
            _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                       expect_position=pos, expect_op=c.OP_ATTENTION)
            with open(os.path.join(OUT, "pos%03d.response.c2h.bin" % pos), "wb") as f:
                f.write(resp)
            bit_exact = out == expected
            row = {
                "position": pos, "seq": seq,
                "input_sha256": sha(qkv),
                "golden_sha256": sha(expected),
                "board_sha256": sha(out),
                "bit_exact": bit_exact,
                "mismatch_bytes": sum(a != b for a, b in zip(out, expected)),
                "transport_total_s": timing.total_s,
            }
            summary["rows"].append(row)
            print("pos=%d seq=%d bit_exact=%s board_sha=%s total_ms=%.3f" % (
                pos, seq, bit_exact, row["board_sha256"][:16], timing.total_s * 1e3))
            if not bit_exact:
                raise RuntimeError("GOLDEN_MISMATCH at position %d (%d bytes differ)" % (
                    pos, row["mismatch_bytes"]))
        summary["status"] = "PASS_U_NPU_GOLDEN_POS0_7_BIT_EXACT"
        summary["final_reset_seq"] = tr.next_seq
        final = tr.reset_cache(timeout_s=TIMEOUT)
        summary["final_reset_total_s"] = final.total_s
    except Exception as exc:
        msg = str(exc)
        if "GOLDEN_MISMATCH" in msg:
            kind = "GOLDEN_MISMATCH"
        elif "C2H" in msg or "read" in msg.lower():
            kind = "C2H_TIMEOUT"
        elif "H2C" in msg or "write" in msg.lower():
            kind = "H2C_TIMEOUT"
        else:
            kind = type(exc).__name__
        summary["status"] = "FAIL_" + kind
        summary["failure"] = {"type": kind, "exception": type(exc).__name__,
                              "message": msg, "active": active,
                              "transport_state": tr.state.value, "next_seq": tr.next_seq}
        try:
            summary["diagnostics_dir"] = save_diagnostics(
                OUT, "first_c2h_timeout" if kind == "C2H_TIMEOUT" else "first_failure",
                active, {"type": kind, "message": msg}, tr)
        except Exception as dexc:
            summary["diagnostics_error"] = repr(dexc)
    finally:
        try:
            dev.close()
        except Exception:
            pass
        summary["bar0_after"] = read_regs()
        with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(json.dumps({k: summary.get(k) for k in
                          ("status", "diagnostics_dir", "bar0_after")}))
        print("SUMMARY=" + os.path.join(OUT, "summary.json"))
    return 0 if summary["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
