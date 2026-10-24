#!/usr/bin/env python3
import hashlib
import json
import math
import os
import struct
import sys
import time

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_metrics_20261024"
PREV = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_20261024/summary.json"
TIMEOUT = 10.0
N = 256
START = 11450
SELECT = (0, 1, 2, 3, 7, 15, 31, 63, 127, 191, 255)

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
import reference as ref
from vectors import tensor

os.makedirs(OUT, exist_ok=True)
os.makedirs(OUT + "/outputs", exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


prev = json.load(open(PREV, encoding="utf-8"))
prev_sha = {r["position"]: r["output_sha256"] for r in prev["passes"][0]["rows"]}

binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {"real_date_utc": "2026-10-24", "start_seq": START, "positions": N,
           "note": "B-mode reference is diagnostic only; it is NOT a U golden",
           "selected": [], "status": "running"}

hist_fixed, hist_float = [], []
try:
    rt = tr.reset_cache(timeout_s=TIMEOUT)
    for pos in range(N):
        payload = tensor(pos, "T2")
        seq = tr.next_seq
        resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
        _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                   expect_position=pos, expect_op=c.OP_ATTENTION)
        with open(OUT + "/outputs/pos%03d.bin" % pos, "wb") as f:
            f.write(out)
        vals = struct.unpack("<576e", out)
        (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(payload)
        hist_fixed.append((ki, vi))
        hist_float.append((kf, vf))
        if pos in SELECT:
            b_fixed = ref.response(qi, hist_fixed, 3)
            b_float = ref.floating(qf, hist_float)
            bv = struct.unpack("<576e", b_fixed)
            diffs = [a - b for a, b in zip(vals, bv)]
            row = {
                "position": pos, "seq": seq, "output_sha256": sha(out),
                "matches_previous_pass": sha(out) == prev_sha.get(pos),
                "transport_total_ms": timing.total_s * 1e3,
                "u_vs_B_fixed_max_abs": max(map(abs, diffs)),
                "u_vs_B_fixed_rmse": (sum(d * d for d in diffs) / 576) ** 0.5,
                "u_vs_float": ref.metrics(vals, b_float),
                "finite": all(math.isfinite(x) for x in vals),
            }
            summary["selected"].append(row)
            print(json.dumps(row))
    summary["status"] = "pass"
except Exception as exc:
    summary["status"] = "failed"
    summary["failure"] = {"type": type(exc).__name__, "message": str(exc),
                          "transport_state": tr.state.value, "next_seq": tr.next_seq}
finally:
    try:
        fseq = tr.next_seq
        tr.reset_cache(timeout_s=TIMEOUT)
        summary["final_reset_seq"] = fseq
    except Exception as exc:
        summary["final_reset_error"] = str(exc)
    try:
        dev.close()
    except Exception:
        pass
    fd = os.open("/dev/ANLOGIC-PCI0_user", os.O_RDONLY)
    try:
        ver = struct.unpack("<I", os.pread(fd, 4, 0xAC))[0]
        st = struct.unpack("<I", os.pread(fd, 4, 0xA4))[0]
        summary["version"] = "0x%08X" % ver
        summary["status_reg"] = "0x%08X" % st
    finally:
        os.close(fd)
    with open(OUT + "/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({"status": summary.get("status"),
                      "final_reset_seq": summary.get("final_reset_seq"),
                      "version": summary.get("version"),
                      "status_reg": summary.get("status_reg")}))
    print("SUMMARY=" + OUT + "/summary.json")
