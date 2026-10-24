#!/usr/bin/env python3
import hashlib
import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
GOLD_U = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_npu_v40_capture_golden"
B_P0 = "/home/kvdev/work_pc1_npu/full-text-v44-planb.q4RMWe/host/.fixtures/v44_probe/attention_l0_p0.output.bin"
OUT = "/home/kvdev/pcie_bringup_20261024/m_attention_probe_20261024"
START = 16100
TIMEOUT = 12.0

sys.path.insert(0, PKG)
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport

os.makedirs(OUT, exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    with open(p, "rb") as f:
        return f.read()


u_qkv = [read(os.path.join(GOLD_U, "pos%03d.qkv.fp16.bin" % p)) for p in range(8)]
u_out = [read(os.path.join(GOLD_U, "pos%03d.attention.fp16.bin" % p)) for p in range(8)]
b0 = read(B_P0)
print("U golden pos0 sha", sha(u_out[0]))
print("B pos0 sha", sha(b0))

binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {"real_date_utc": "2026-10-24", "bit": "M (B-burned, hash/policy TBD)",
           "start_seq": START, "passes": [], "status": "running"}
try:
    for run in (1, 2):
        reset_seq = tr.next_seq
        rt = tr.reset_cache(timeout_s=TIMEOUT)
        rows = []
        for pos in range(8):
            seq = tr.next_seq
            resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, u_qkv[pos], timeout_s=TIMEOUT)
            _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                       expect_position=pos, expect_op=c.OP_ATTENTION)
            with open(os.path.join(OUT, "run%d_pos%03d.bin" % (run, pos)), "wb") as f:
                f.write(out)
            row = {"run": run, "position": pos, "seq": seq, "output_sha256": sha(out),
                   "vs_U_bit_exact": out == u_out[pos],
                   "vs_B_p0_bit_exact": (out == b0) if pos == 0 else None,
                   "finite": all(abs(x) < 1e30 for x in struct.unpack("<576e", out)),
                   "transport_total_s": timing.total_s}
            rows.append(row)
            print("run%d pos=%d seq=%d U=%s B0=%s sha=%s total_ms=%.3f" % (
                run, pos, seq, row["vs_U_bit_exact"], row["vs_B_p0_bit_exact"],
                row["output_sha256"][:16], timing.total_s * 1e3))
        summary["passes"].append({"run": run, "reset_seq": reset_seq, "rows": rows})
    summary["deterministic"] = all(
        summary["passes"][0]["rows"][i]["output_sha256"] == summary["passes"][1]["rows"][i]["output_sha256"]
        for i in range(8))
    summary["status"] = "M_PROBE_DONE"
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
    print(json.dumps({k: summary.get(k) for k in ("status", "deterministic", "final_reset_seq")}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
