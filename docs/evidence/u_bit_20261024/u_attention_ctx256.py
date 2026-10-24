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
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_20261024"
TIMEOUT = 10.0
N = 256

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
from vectors import tensor

os.makedirs(OUT, exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = 10900

summary = {
    "real_date_utc": "2026-10-24",
    "bit_sha256_from_B": "B5AD8F911EC270E448993D09C1BC243B4420D873870B3B18D39BD46A2958B26B",
    "mode": "U: K2/V2 all layers/tokens, no FP16 tail, MAX_T=256, SCORE_SHIFT=3",
    "profile": "synthetic T2 vectors, layer0, positions 0..255, two independent RESET sessions",
    "timeout_s": TIMEOUT,
    "status": "running",
    "passes": [],
}

try:
    pass_out = {}
    for run in (1, 2):
        reset_seq = tr.next_seq
        rt = tr.reset_cache(timeout_s=TIMEOUT)
        rows = []
        outs = []
        t_start = time.monotonic()
        for pos in range(N):
            seq = tr.next_seq
            payload = tensor(pos, "T2")
            resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
            _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                       expect_position=pos, expect_op=c.OP_ATTENTION)
            vals = struct.unpack("<576e", out)
            finite = all(math.isfinite(x) for x in vals)
            rows.append({"seq": seq, "position": pos, "output_sha256": sha(out),
                         "finite": finite, "total_s": timing.total_s})
            outs.append(out)
            if pos in (0, 1, 2, 3, 7, 15, 31, 63, 127, 191, 255):
                print("run%d pos=%3d seq=%d finite=%s total_ms=%.3f sha=%s" % (
                    run, pos, seq, finite, timing.total_s * 1e3, sha(out)[:16]))
        elapsed = time.monotonic() - t_start
        summary["passes"].append({
            "run": run, "reset_seq": reset_seq, "attention_seq_first": reset_seq + 1,
            "attention_seq_last": tr.next_seq - 1,
            "elapsed_s": elapsed,
            "concat_output_sha256": sha(b"".join(outs)),
            "rows": rows,
        })
        pass_out[run] = outs
        print("run%d elapsed=%.2fs concat_sha=%s" % (run, elapsed, sha(b"".join(outs))[:16]))
    mismatches = [p for p in range(N) if pass_out[1][p] != pass_out[2][p]]
    summary["deterministic_across_reset"] = (not mismatches)
    summary["mismatch_positions"] = mismatches
    summary["all_finite"] = all(r["finite"] for p in summary["passes"] for r in p["rows"])
    summary["status"] = "pass" if (not mismatches and summary["all_finite"]) else "fail"
except Exception as exc:
    summary["status"] = "failed"
    summary["failure"] = {"type": type(exc).__name__, "message": str(exc),
                          "transport_state": tr.state.value, "next_seq": tr.next_seq}
finally:
    try:
        dev.close()
    except Exception:
        pass
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary[k] for k in
                      ("status", "deterministic_across_reset", "mismatch_positions", "all_finite")
                      if k in summary}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
