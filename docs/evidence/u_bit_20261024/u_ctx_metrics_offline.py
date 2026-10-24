import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024"
sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
import reference as ref
from vectors import tensor

SELECT = (0, 1, 2, 3, 7, 15, 31, 63, 127, 191, 255)
hist_fixed, hist_float = [], []
rows = []
for pos in range(256):
    payload = tensor(pos, "T2")
    (qi, ki, vi), (qf, kf, vf) = ref.decode_payload(payload)
    hist_fixed.append((ki, vi))
    hist_float.append((kf, vf))
    if pos not in SELECT:
        continue
    with open(OUT + "/outputs/pos%03d.bin" % pos, "rb") as f:
        out = f.read()
    uv = struct.unpack("<576e", out)
    bv = struct.unpack("<576e", ref.response(qi, hist_fixed, 3))
    diffs = [a - b for a, b in zip(uv, bv)]
    row = {
        "position": pos,
        "u_output_sha256": __import__("hashlib").sha256(out).hexdigest(),
        "u_vs_B_fixed_max_abs": max(map(abs, diffs)),
        "u_vs_B_fixed_rmse": (sum(d * d for d in diffs) / 576) ** 0.5,
        "u_vs_float": ref.metrics(uv, ref.floating(qf, hist_float)),
    }
    rows.append(row)
    print(json.dumps(row))
with open(OUT + "/u_vs_B_metrics.json", "w", encoding="utf-8") as f:
    json.dump({"note": "B-mode reference is diagnostic only, NOT a U golden", "rows": rows}, f, indent=2)
