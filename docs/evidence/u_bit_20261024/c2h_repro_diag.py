#!/usr/bin/env python3
"""Bounded C2H-timeout reproducer with first-failure diagnostics.

Same host-side interleaving that preceded the 2026-10-24 C2H poll-mode timeout:
256 T2 positions per pass, computing the Python B reference at selected positions.
Any failure stops the run and saves diagnostics before closing the device.
No retry, no reset, no driver recovery.
"""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
GOLD = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_t2_256_golden.json"
OUT = "/home/kvdev/pcie_bringup_20261024/c2h_repro_20261024"
START = 12600
PASSES = 3
N = 256
TIMEOUT = 12.0
SELECT = (0, 1, 2, 3, 7, 15, 31, 63, 127, 191, 255)
REG_OFFSETS = (0x5C, 0x74, 0x84, 0x90, 0x94, 0x98, 0x9C, 0xA0, 0xA4, 0xA8, 0xAC, 0xB0)

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
import reference as ref
from vectors import tensor


def sha(b):
    return hashlib.sha256(b).hexdigest()


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


def save_diagnostics(root, label, active, err, tr, last_rows):
    d = os.path.join(root, "diag_" + label)
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
    base = "/sys/bus/pci/devices/0000:21:00.0"
    sysfs = os.path.join(d, "sysfs")
    os.makedirs(sysfs, exist_ok=True)
    for name in ("vendor", "device", "class", "current_link_speed", "current_link_width",
                 "resource", "irq", "enable"):
        try:
            shutil.copyfile(os.path.join(base, name), os.path.join(sysfs, name))
        except Exception:
            pass
    with open(os.path.join(d, "last_rows.json"), "w", encoding="utf-8") as f:
        json.dump(last_rows[-32:], f, indent=2)
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
        "last_rows_tail": last_rows[-8:],
        "note": "No retry, no reset, no driver recovery was attempted after this failure.",
    }
    with open(os.path.join(d, "diagnostic.json"), "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2)
    return d


def main():
    if os.path.exists(OUT):
        raise SystemExit("refusing to overwrite existing OUT: " + OUT)
    os.makedirs(OUT + "/outputs")
    gold = json.load(open(GOLD, encoding="utf-8"))
    gold_sha = {r["position"]: r["output_sha256"] for r in gold["rows"]}
    if len(gold_sha) != 256:
        raise SystemExit("T2 golden must have 256 rows")

    binding = Binding.load(BINDING)
    dev = SgdmaDevice(binding)
    tr = Transport(dev, binding)
    tr.next_seq = START
    summary = {
        "real_date_utc": "2026-10-24",
        "purpose": "bounded C2H timeout reproducer with first-failure diagnostics",
        "golden": GOLD,
        "start_seq": START, "passes": PASSES, "positions": N,
        "timeout_s": TIMEOUT, "status": "running", "pass_rows": [],
    }
    active = None
    last_rows = []
    try:
        for run_i in range(1, PASSES + 1):
            reset_seq = tr.next_seq
            rt = tr.reset_cache(timeout_s=TIMEOUT)
            rows = []
            outs = []
            hist_fixed, hist_float = [], []
            t0 = time.monotonic()
            for pos in range(N):
                seq = tr.next_seq
                active = {"run": run_i, "position": pos, "seq": seq}
                payload = tensor(pos, "T2")
                resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
                _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                           expect_position=pos, expect_op=c.OP_ATTENTION)
                with open(OUT + "/outputs/run%d_pos%03d.bin" % (run_i, pos), "wb") as f:
                    f.write(out)
                outs.append(out)
                (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(payload)
                hist_fixed.append((ki, vi))
                hist_float.append((kf, vf))
                metric = None
                if pos in SELECT:
                    b_fixed = struct.unpack("<576e", ref.response(qi, hist_fixed, 3))
                    u_vals = struct.unpack("<576e", out)
                    diffs = [a - b for a, b in zip(u_vals, b_fixed)]
                    metric = {"max_abs_vs_B": max(map(abs, diffs)),
                              "rmse_vs_B": (sum(d * d for d in diffs) / 576) ** 0.5}
                    # extra host-side work, like the run that first timed out
                    ref.floating(qf, hist_float)
                row = {"run": run_i, "position": pos, "seq": seq,
                       "output_sha256": sha(out),
                       "matches_t2_golden": sha(out) == gold_sha.get(pos),
                       "transport_total_s": timing.total_s, "metric": metric}
                rows.append(row)
                last_rows.append(row)
                if pos % 32 == 0 or pos in SELECT:
                    print("run%d pos=%3d seq=%d golden=%s total_ms=%.3f" % (
                        run_i, pos, seq, row["matches_t2_golden"], timing.total_s * 1e3))
            concat = sha(b"".join(outs)) if len(outs) == N else None
            summary["pass_rows"].append({
                "run": run_i, "reset_seq": reset_seq,
                "attention_seq_first": reset_seq + 1,
                "attention_seq_last": tr.next_seq - 1,
                "elapsed_s": time.monotonic() - t0,
                "concat_output_sha256": concat,
                "all_match_t2_golden": all(r["matches_t2_golden"] for r in rows),
                "rows": rows,
            })
            if not all(r["matches_t2_golden"] for r in rows):
                raise RuntimeError("T2_GOLDEN_MISMATCH in run %d" % run_i)
            print("run%d elapsed=%.2fs concat=%s" % (run_i, time.monotonic() - t0, concat))
        summary["status"] = "NO_C2H_TIMEOUT_DURING_%d_PASSES" % PASSES
        summary["final_reset_seq"] = tr.next_seq
        summary["final_reset_total_s"] = tr.reset_cache(timeout_s=TIMEOUT).total_s
    except Exception as exc:
        msg = str(exc)
        if "T2_GOLDEN_MISMATCH" in msg:
            kind = "T2_GOLDEN_MISMATCH"
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
        summary["partial_rows"] = last_rows[-32:]
        try:
            summary["diagnostics_dir"] = save_diagnostics(
                OUT, "first_c2h_timeout" if kind == "C2H_TIMEOUT" else "first_failure",
                active, {"type": kind, "message": msg}, tr, last_rows)
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
    return 0 if str(summary["status"]).startswith("NO_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
