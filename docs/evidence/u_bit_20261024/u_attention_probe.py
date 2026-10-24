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
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_probe_20261024"
START_SEQ = 10100
POSITIONS = 8
TIMEOUT = 5.0

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
tr.next_seq = START_SEQ

summary = {
    "real_date_utc": "2026-10-24",
    "bit_file_from_B": "attention_planb_full.bit",
    "bit_sha256_from_B_not_board_read": "B5AD8F911EC270E448993D09C1BC243B4420D873870B3B18D39BD46A2958B26B",
    "mode_from_B": "U: K2/V2 all layers/tokens, no FP16 tail, MAX_T=256, SCORE_SHIFT=3",
    "profile": "wire FP16 Q[9,64] K/V[3,64]; synthetic T2 vectors; positions 0..7; NOT compared to a U golden here",
    "binding": BINDING,
    "start_seq": START_SEQ,
    "positions": POSITIONS,
    "timeout_s": TIMEOUT,
    "passes": [],
    "status": "running",
}

try:
    for run in (1, 2):
        reset_seq = tr.next_seq
        rt = tr.reset_cache(timeout_s=TIMEOUT)
        rows = []
        run_out = []
        for pos in range(POSITIONS):
            seq = tr.next_seq
            payload = tensor(pos, "T2")
            t0 = time.monotonic()
            resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
            _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                       expect_position=pos, expect_op=c.OP_ATTENTION)
            words = struct.unpack("<576H", out)
            vals = struct.unpack("<576e", out)
            finite = all(math.isfinite(x) for x in vals)
            stem = "%04d_attention_l0_p%d" % (seq, pos)
            with open(os.path.join(OUT, stem + ".h2c.bin"), "wb") as f:
                f.write(c.pack_request(seq, 0, pos, payload, op=c.OP_ATTENTION))
            with open(os.path.join(OUT, stem + ".c2h.bin"), "wb") as f:
                f.write(resp)
            row = {
                "run": run, "seq": seq, "position": pos,
                "input_sha256": sha(payload), "output_sha256": sha(out),
                "fp16_words_hex": ["%04x" % w for w in words],
                "fp16_values": [x if math.isfinite(x) else str(x) for x in vals],
                "finite": finite,
                "transport_total_s": timing.total_s,
            }
            with open(os.path.join(OUT, stem + ".json"), "w", encoding="utf-8") as f:
                json.dump(row, f, indent=2)
            rows.append(row)
            run_out.append(out)
            print("run%d pos%d seq=%d out_sha=%s finite=%s total_ms=%.3f" % (
                run, pos, seq, row["output_sha256"][:16], finite, timing.total_s * 1e3))
        summary["passes"].append({
            "run": run, "reset_seq": reset_seq, "reset_total_s": rt.total_s,
            "rows": [{k: r[k] for k in ("seq", "position", "input_sha256", "output_sha256",
                                         "finite", "transport_total_s")} for r in rows],
            "concat_output_sha256": sha(b"".join(run_out)),
        })
        if run == 1:
            first = run_out
        else:
            summary["deterministic_across_reset"] = (first == run_out)
    summary["status"] = "probe_done"
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
    print(json.dumps({k: summary[k] for k in ("status", "deterministic_across_reset") if k in summary}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
