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
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024"
TIMEOUT = 10.0
N = 256
START = 11500

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
from vectors import tensor

os.makedirs(OUT + "/outputs", exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {"real_date_utc": "2026-10-24", "start_seq": START, "positions": N,
           "profile": "synthetic T2, layer0, no B-reference computation during the pass",
           "status": "running", "rows": []}
try:
    reset_seq = tr.next_seq
    rt = tr.reset_cache(timeout_s=TIMEOUT)
    t0 = time.monotonic()
    for pos in range(N):
        seq = tr.next_seq
        payload = tensor(pos, "T2")
        resp, timing = tr.round_trip(c.OP_ATTENTION, 0, pos, payload, timeout_s=TIMEOUT)
        _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=0,
                                   expect_position=pos, expect_op=c.OP_ATTENTION)
        with open(OUT + "/outputs/pos%03d.bin" % pos, "wb") as f:
            f.write(out)
        vals = struct.unpack("<576e", out)
        row = {"seq": seq, "position": pos, "output_sha256": sha(out),
               "finite": all(math.isfinite(x) for x in vals),
               "transport_total_s": timing.total_s}
        summary["rows"].append(row)
        if pos in (0, 1, 2, 3, 7, 15, 31, 63, 127, 191, 255):
            print("pos=%3d seq=%d finite=%s total_ms=%.3f sha=%s" % (
                pos, seq, row["finite"], timing.total_s * 1e3, row["output_sha256"][:16]))
    summary["elapsed_s"] = time.monotonic() - t0
    summary["concat_output_sha256"] = sha(b"".join(
        open(OUT + "/outputs/pos%03d.bin" % p, "rb").read() for p in range(N)))
    summary["all_finite"] = all(r["finite"] for r in summary["rows"])
    summary["status"] = "pass" if summary["all_finite"] else "fail"
    summary["final_reset_seq"] = tr.next_seq
    tr.reset_cache(timeout_s=TIMEOUT)
except Exception as exc:
    summary["status"] = "failed"
    summary["failure"] = {"type": type(exc).__name__, "message": str(exc),
                          "transport_state": tr.state.value, "next_seq": tr.next_seq}
finally:
    try:
        dev.close()
    except Exception:
        pass
    fd = os.open("/dev/ANLOGIC-PCI0_user", os.O_RDONLY)
    try:
        summary["version"] = "0x%08X" % struct.unpack("<I", os.pread(fd, 4, 0xAC))[0]
        summary["status_reg"] = "0x%08X" % struct.unpack("<I", os.pread(fd, 4, 0xA4))[0]
    finally:
        os.close(fd)
    with open(OUT + "/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary.get(k) for k in
                      ("status", "elapsed_s", "all_finite", "concat_output_sha256",
                       "final_reset_seq", "version", "status_reg")}))
    print("SUMMARY=" + OUT + "/summary.json")
