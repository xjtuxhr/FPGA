#!/usr/bin/env python3
"""M-bit layer sweep: T2 positions 0..63 for each layer 0..29.

Classifies each layer by whether post-tail outputs match the U golden (K2/V2)
or diverge from both B and U (layer-aware mixed path). No M golden is claimed.
"""
import hashlib
import json
import os
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
GOLD_U = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_t2_256_golden.json"
OUT = "/home/kvdev/pcie_bringup_20261024/m_layer_sweep_20261024"
START = 16300
N = 64
LAYERS = 30
TIMEOUT = 12.0
TAIL = 32

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport
import reference as ref
from vectors import tensor

os.makedirs(OUT + "/outputs", exist_ok=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


gold = json.load(open(GOLD_U, encoding="utf-8"))
u_sha = {r["position"]: r["output_sha256"] for r in gold["rows"]}

# Precompute B reference and payloads for T2 0..63.
payloads = [tensor(p, "T2") for p in range(N)]
hist_fixed, hist_float = [], []
b_out = []
for p in range(N):
    (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(payloads[p])
    hist_fixed.append((ki, vi))
    hist_float.append((kf, vf))
    b_out.append(ref.response(qi, hist_fixed, 3))

binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
summary = {
    "real_date_utc": "2026-10-24",
    "bit": "M (attention_planb_full.bit)",
    "bit_path_from_user": r"E:\KVmix\um_td_planb_m_readeraddr_20261023\attention_planb_full.bit",
    "bit_sha256_from_user_not_board_read": "67C149839565425CE450BFBCA1E998C58F4700DE0689F0A07FDC057215BBFAB1",
    "profile": "T2 synthetic, positions 0..63, layers 0..29, MAX_T=256 inferred, no M golden",
    "tail_hypothesis": TAIL,
    "start_seq": START,
    "status": "running",
    "layers": [],
}
try:
    for layer in range(LAYERS):
        reset_seq = tr.next_seq
        tr.reset_cache(timeout_s=TIMEOUT)
        rows = []
        for pos in range(N):
            seq = tr.next_seq
            resp, timing = tr.round_trip(c.OP_ATTENTION, layer, pos, payloads[pos], timeout_s=TIMEOUT)
            _, out = c.unpack_response(resp, expect_seq=seq, expect_layer=layer,
                                       expect_position=pos, expect_op=c.OP_ATTENTION)
            with open(os.path.join(OUT, "outputs/layer%02d_pos%03d.bin" % (layer, pos)), "wb") as f:
                f.write(out)
            rows.append({"position": pos, "seq": seq, "sha256": sha(out),
                         "vs_B": out == b_out[pos],
                         "vs_U": sha(out) == u_sha.get(pos),
                         "transport_total_s": timing.total_s})
        b_prefix = 0
        for r in rows:
            if r["vs_B"]:
                b_prefix += 1
            else:
                break
        post = rows[TAIL:]
        rec = {
            "layer": layer, "reset_seq": reset_seq,
            "B_exact_prefix_len": b_prefix,
            "B_exact_post_tail": sum(1 for r in post if r["vs_B"]),
            "U_exact_post_tail": sum(1 for r in post if r["vs_U"]),
            "M_distinct_post_tail": sum(1 for r in post if not r["vs_B"] and not r["vs_U"]),
            "first_post_tail_divergence": next((r["position"] for r in post if not r["vs_B"]), None),
            "post_tail_class": ("U_EQUIVALENT" if all(r["vs_U"] for r in post)
                                else "M_DISTINCT" if all(not r["vs_B"] and not r["vs_U"] for r in post)
                                else "MIXED"),
            "rows": rows,
        }
        summary["layers"].append(rec)
        print("layer=%2d B_prefix=%d B_post=%d U_post=%d M_distinct=%d class=%s" % (
            layer, b_prefix, rec["B_exact_post_tail"], rec["U_exact_post_tail"],
            rec["M_distinct_post_tail"], rec["post_tail_class"]))
    summary["status"] = "M_LAYER_SWEEP_DONE"
    summary["final_reset_seq"] = tr.next_seq
    tr.reset_cache(timeout_s=TIMEOUT)
except Exception as exc:
    summary["status"] = "FAILED"
    summary["failure"] = {"type": type(exc).__name__, "message": str(exc),
                          "transport_state": tr.state.value, "next_seq": tr.next_seq,
                          "layer": layer if 'layer' in locals() else None}
finally:
    try:
        dev.close()
    except Exception:
        pass
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if summary.get("layers"):
        print("classes:", [(x["layer"], x["post_tail_class"]) for x in summary["layers"]])
    print(json.dumps({k: summary.get(k) for k in
                      ("status", "final_reset_seq", "failure") if k in summary}))
    print("SUMMARY=" + os.path.join(OUT, "summary.json"))
