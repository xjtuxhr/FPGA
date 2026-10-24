import hashlib
import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
ROOT = "/home/kvdev/pcie_bringup_20261024/v44_real_npu_qkv_for_m"
OUT = "/home/kvdev/pcie_bringup_20261024/m_real_npu_30layer_20261024"
RESULT = os.path.join(OUT, "vs_B_reference.json")

sys.path.insert(0, PKG)
sys.path.insert(0, PKG + "/board_attention")
import reference as ref

manifest = json.load(open(os.path.join(ROOT, "manifest.json"), encoding="utf-8"))
records = manifest["records"]
by_req = {}
for r in records:
    by_req.setdefault(r["request"], {}).setdefault(r["position"], {})[r["layer"]] = r

mismatches = []
per_layer = {}
total = 0
for req in sorted(by_req):
    hist_fixed = {}  # RESET before each request clears all layer KV
    for pos in sorted(by_req[req]):
        for layer in sorted(by_req[req][pos]):
            rec = by_req[req][pos][layer]
            qkv = open(os.path.join(ROOT, rec["file"]), "rb").read()
            (qi, ki, vi), _ = ref.decode_payload(qkv)
            h = hist_fixed.setdefault(layer, [])
            h.append((ki, vi))
            expected = ref.response(qi, h, 3)
            name = "r%d_p%03d_l%02d.bin" % (req, pos, layer)
            actual = open(os.path.join(OUT, "outputs", name), "rb").read()
            total += 1
            ok = actual == expected
            s = per_layer.setdefault(layer, {"frames": 0, "bit_exact": 0, "mismatch": 0})
            s["frames"] += 1
            s["bit_exact" if ok else "mismatch"] += 1
            if not ok:
                mismatches.append({
                    "request": req, "position": pos, "layer": layer,
                    "file": name,
                    "actual_sha256": hashlib.sha256(actual).hexdigest(),
                    "expected_sha256": hashlib.sha256(expected).hexdigest(),
                    "mismatch_bytes": sum(a != b for a, b in zip(actual, expected)),
                })
result = {
    "note": "B reference, not an independent M golden. All positions <=10 < M tail R=32.",
    "total_frames": total,
    "bit_exact": total - len(mismatches),
    "mismatch_count": len(mismatches),
    "all_bit_exact": not mismatches,
    "per_layer": {str(k): v for k, v in sorted(per_layer.items())},
    "mismatches": mismatches[:50],
    "status": ("PASS_M_REAL_NPU_TAIL_BIT_EXACT" if not mismatches
               else "FAIL_M_REAL_NPU_TAIL_VS_B_REFERENCE"),
}
with open(RESULT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: result[k] for k in
                  ("status", "total_frames", "bit_exact", "mismatch_count", "all_bit_exact")}))
print("RESULT=" + RESULT)
