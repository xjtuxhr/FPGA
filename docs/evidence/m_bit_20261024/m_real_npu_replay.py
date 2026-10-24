#!/usr/bin/env python3
"""Fixed replay of v44 real-NPU QKV on the M bit, positions then layers.

No M golden is included. This runner only executes and stores board outputs;
a separate offline step compares them to the B reference (positions <=10 are
inside the M recent FP16 tail R=32).
"""
import hashlib
import json
import math
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
ROOT = "/home/kvdev/pcie_bringup_20261024/v44_real_npu_qkv_for_m"
OUT = "/home/kvdev/pcie_bringup_20261024/m_real_npu_30layer_20261024"
START = 18300
TIMEOUT = 12.0

sys.path.insert(0, PKG)
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport

os.makedirs(OUT + "/outputs", exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    with open(p, "rb") as f:
        return f.read()


manifest = json.load(open(os.path.join(ROOT, "manifest.json"), encoding="utf-8"))
if manifest.get("m_expected_outputs_included") is not False:
    raise SystemExit("unexpected manifest: M expected outputs flag")
if manifest.get("source_real_npu") is not True:
    raise SystemExit("manifest does not claim real NPU source")
records = manifest["records"]
# Verify every QKV record before touching the device.
by_req = {}
for r in records:
    qkv = read(os.path.join(ROOT, r["file"]))
    if len(qkv) != r["bytes"] or sha(qkv) != r["sha256"]:
        raise SystemExit("QKV hash/length mismatch: %s" % r["file"])
    by_req.setdefault(r["request"], {}).setdefault(r["position"], {})[r["layer"]] = (r, qkv)
print("verified %d QKV records, requests=%s" % (len(records), sorted(by_req)))

binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {
    "real_date_utc": "2026-10-24",
    "bit": "M attention_planb_full.bit",
    "bit_sha256_from_user": "67C149839565425CE450BFBCA1E998C58F4700DE0689F0A07FDC057215BBFAB1",
    "bit_path_from_user": r"E:\KVmix\um_td_planb_m_readeraddr_20261023\attention_planb_full.bit",
    "manifest": os.path.join(ROOT, "manifest.json"),
    "manifest_schema": manifest.get("schema"),
    "source_status": manifest.get("source_status"),
    "m_expected_outputs_included": manifest.get("m_expected_outputs_included"),
    "start_seq": START,
    "timeout_s": TIMEOUT,
    "status": "running",
    "requests": [],
}
try:
    for req in sorted(by_req):
        positions = by_req[req]
        reset_seq = tr.next_seq
        tr.reset_cache(timeout_s=TIMEOUT)
        req_rows = []
        for pos in sorted(positions):
            for layer in sorted(positions[pos]):
                rec, qkv = positions[pos][layer]
                seq = tr.next_seq
                resp, timing = tr.round_trip(c.OP_ATTENTION, layer, pos, qkv, timeout_s=TIMEOUT)
                _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=layer,
                                           expect_position=pos, expect_op=c.OP_ATTENTION)
                name = "r%d_p%03d_l%02d.bin" % (req, pos, layer)
                with open(os.path.join(OUT, "outputs", name), "wb") as f:
                    f.write(out)
                vals = struct.unpack("<576e", out)
                row = {"request": req, "position": pos, "layer": layer, "seq": seq,
                       "token_id": rec.get("token_id"), "output_file": name,
                       "output_sha256": sha(out),
                       "finite": all(math.isfinite(x) for x in vals),
                       "transport_total_s": timing.total_s}
                req_rows.append(row)
        summary["requests"].append({"request": req, "reset_seq": reset_seq,
                                    "positions": sorted(positions),
                                    "frames": len(req_rows), "rows": req_rows})
        print("request=%d reset=%d frames=%d positions=%s" % (
            req, reset_seq, len(req_rows), [min(positions), max(positions)]))
    summary["status"] = "M_REAL_NPU_REPLAY_DONE"
    summary["total_frames"] = sum(r["frames"] for r in summary["requests"])
    summary["all_finite"] = all(row["finite"] for r in summary["requests"] for row in r["rows"])
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
                      ("status", "total_frames", "all_finite", "final_reset_seq", "failure")
                      if k in summary}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
