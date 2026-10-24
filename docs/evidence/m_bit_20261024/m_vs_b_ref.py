import hashlib
import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
GOLD = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_npu_v40_capture_golden"
M = "/home/kvdev/pcie_bringup_20261024/m_attention_probe_20261024"
B_P0 = "/home/kvdev/work_pc1_npu/full-text-v44-planb.q4RMWe/host/.fixtures/v44_probe/attention_l0_p0.output.bin"
OUT = "/home/kvdev/pcie_bringup_20261024/m_attention_probe_20261024/m_vs_B_reference.json"

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
import reference as ref

hist_fixed, hist_float = [], []
rows = []
for pos in range(8):
    qkv = open(os.path.join(GOLD, "pos%03d.qkv.fp16.bin" % pos), "rb").read()
    (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(qkv)
    hist_fixed.append((ki, vi))
    hist_float.append((kf, vf))
    b_fixed = ref.response(qi, hist_fixed, 3)
    b_float = ref.floating(qf, hist_float)
    m = open(os.path.join(M, "run1_pos%03d.bin" % pos), "rb").read()
    mv = struct.unpack("<576e", m)
    row = {
        "position": pos,
        "m_sha256": hashlib.sha256(m).hexdigest(),
        "b_ref_sha256": hashlib.sha256(b_fixed).hexdigest(),
        "m_vs_B_ref_bit_exact": m == b_fixed,
        "m_vs_B_ref_mismatch_bytes": sum(a != b for a, b in zip(m, b_fixed)),
        "m_vs_B_float": ref.metrics(mv, b_float),
    }
    if pos == 0:
        b0 = open(B_P0, "rb").read()
        row["B_bit_pos0_sha256"] = hashlib.sha256(b0).hexdigest()
        row["B_ref_vs_B_bit_pos0_bit_exact"] = (b_fixed == b0)
    rows.append(row)
    print(json.dumps(row))
result = {"note": "B reference is the FP16/B candidate; M recent-tail subrange is expected to match it",
          "rows": rows}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print("RESULT=" + OUT)
