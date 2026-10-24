#!/usr/bin/env python3
import hashlib
import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
GOLD_U = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_t2_256_golden.json"
OUT = "/home/kvdev/pcie_bringup_20261024/m_tail_probe_20261024"
START = 16200
N = 64
TIMEOUT = 12.0

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
import reference as ref
from vectors import tensor

os.makedirs(OUT, exist_ok=True)
gold = json.load(open(GOLD_U, encoding="utf-8"))
u_sha = {r["position"]: r["output_sha256"] for r in gold["rows"]}


def sha(b):
    return hashlib.sha256(b).hexdigest()


binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {"real_date_utc": "2026-10-24", "bit": "M (B-burned, hash/policy TBD)",
           "profile": "T2 synthetic, layer0, positions 0..63; no M golden",
           "start_seq": START, "positions": N, "status": "running", "rows": []}
hist_fixed, hist_float = [], []
try:
    reset_seq = tr.next_seq
    tr.reset_cache(timeout_s=TIMEOUT)
    for pos in range(N):
        seq = tr.next_seq
        payload = tensor(pos, "T2")
        resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
        _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                   expect_position=pos, expect_op=c.OP_ATTENTION)
        with open(os.path.join(OUT, "pos%03d.bin" % pos), "wb") as f:
            f.write(out)
        (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(payload)
        hist_fixed.append((ki, vi))
        hist_float.append((kf, vf))
        b_fixed = ref.response(qi, hist_fixed, 3)
        row = {"position": pos, "seq": seq, "m_sha256": sha(out),
               "b_ref_sha256": sha(b_fixed), "vs_B_exact": out == b_fixed,
               "vs_U_golden": sha(out) == u_sha.get(pos),
               "transport_total_s": timing.total_s}
        summary["rows"].append(row)
        print("pos=%2d seq=%d B=%s U=%s m=%s total_ms=%.3f" % (
            pos, seq, row["vs_B_exact"], row["vs_U_golden"], row["m_sha256"][:16],
            timing.total_s * 1e3))
    summary["status"] = "M_TAIL_PROBE_DONE"
    b_positions = [r["position"] for r in summary["rows"] if r["vs_B_exact"]]
    summary["B_exact_positions"] = b_positions
    summary["B_exact_prefix_len"] = 0
    for p in range(N):
        if p in b_positions:
            summary["B_exact_prefix_len"] = p + 1
        else:
            break
    summary["U_exact_positions"] = [r["position"] for r in summary["rows"] if r["vs_U_golden"]]
    summary["final_reset_seq"] = tr.next_seq
    tr.reset_cache(timeout_s=TIMEOUT)
except Exception as exc:
    summary["status"] = "FAILED"
    summary["failure"] = {"type": type(exc).__name__, "message": str(exc),
                          "transport_state": tr.state.value, "next_seq": tr.next_seq}
finally:
    try:
        dev.close()
    except Exception:
        pass
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary.get(k) for k in
                      ("status", "B_exact_prefix_len", "B_exact_positions",
                       "U_exact_positions", "final_reset_seq")}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
