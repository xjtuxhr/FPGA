import hashlib
import json
import os
import struct
import sys

GOLD = "/home/kvdev/pcie_bringup_20261024/m_v44_real_npu_golden_20261024"
QKV = "/home/kvdev/pcie_bringup_20261024/v44_real_npu_qkv_for_m/qkv"
ACT = "/home/kvdev/pcie_bringup_20261024/m_real_npu_30layer_20261024/outputs"
RESULT = "/home/kvdev/pcie_bringup_20261024/m_real_npu_30layer_20261024/vs_M_golden.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    with open(p, "rb") as f:
        return f.read()


m = json.load(open(os.path.join(GOLD, "manifest.json"), encoding="utf-8"))
expected_blob = read(os.path.join(GOLD, m["expected_output_blob"]))
input_blob = read(os.path.join(GOLD, m["input_blob"]))
if sha(expected_blob) != m["expected_output_blob_sha256"]:
    raise SystemExit("expected blob SHA mismatch")
if sha(input_blob) != m["input_blob_sha256"]:
    raise SystemExit("input blob SHA mismatch")
if len(expected_blob) != m["frames"] * 1152 or len(input_blob) != m["frames"] * 1920:
    raise SystemExit("blob length mismatch")

mismatches = []
input_mismatches = []
per_layer = {}
per_request = {}
bits = {}
quantized = 0
for r in m["records"]:
    req, pos, layer = r["request"], r["position"], r["layer"]
    name = "r%d_p%03d_l%02d.bin" % (req, pos, layer)
    actual = read(os.path.join(ACT, name))
    off = r["expected_output_offset"]
    expected = expected_blob[off:off + 1152]
    key = "r%d_p%03d_l%02d" % (req, pos, layer)
    qkv_actual = read(os.path.join(QKV, key + ".fp16.bin"))
    io = r["input_offset"]
    qkv_expected = input_blob[io:io + 1920]
    if qkv_actual != qkv_expected or sha(qkv_actual) != r["input_sha256"]:
        input_mismatches.append(name)
    if sha(expected) != r["expected_output_sha256"]:
        raise SystemExit("record expected SHA mismatch: " + name)
    ok = actual == expected
    s = per_layer.setdefault(layer, {"frames": 0, "bit_exact": 0, "mismatch": 0})
    s["frames"] += 1
    s["bit_exact" if ok else "mismatch"] += 1
    q = per_request.setdefault(req, {"frames": 0, "bit_exact": 0, "mismatch": 0})
    q["frames"] += 1
    q["bit_exact" if ok else "mismatch"] += 1
    b = "%dK/%dV" % (r["k_bits_configured"], r["v_bits_configured"])
    bits[b] = bits.get(b, 0) + 1
    if r["kv_actually_quantized"]:
        quantized += 1
    if not ok:
        mismatches.append({
            "request": req, "position": pos, "layer": layer, "file": name,
            "actual_sha256": sha(actual), "expected_sha256": sha(expected),
            "mismatch_bytes": sum(a != b for a, b in zip(actual, expected)),
            "first_mismatch": next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b), None),
        })

result = {
    "real_date_utc": "2026-10-24",
    "golden_status": m.get("status"),
    "policy_status": m.get("policy_status"),
    "policy_sha256": m.get("policy_sha256"),
    "tail_length": m.get("tail_length"),
    "tail_eviction_covered": m.get("tail_eviction_covered"),
    "m_quantization_exercised": m.get("m_quantization_exercised"),
    "max_position": m.get("max_position"),
    "expected_output_blob_sha256": sha(expected_blob),
    "input_blob_sha256": sha(input_blob),
    "frames": m["frames"],
    "bit_exact": m["frames"] - len(mismatches),
    "mismatch_count": len(mismatches),
    "all_bit_exact": not mismatches,
    "input_frame_mismatches": input_mismatches,
    "per_request": {str(k): v for k, v in sorted(per_request.items())},
    "per_layer": {str(k): v for k, v in sorted(per_layer.items())},
    "bit_config_counts": bits,
    "kv_actually_quantized_frames": quantized,
    "mismatches": mismatches[:50],
    "status": ("PASS_M_V44_REAL_NPU_GOLDEN_630" if not mismatches
               else "FAIL_M_V44_REAL_NPU_GOLDEN"),
}
with open(RESULT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: result[k] for k in
                  ("status", "frames", "bit_exact", "mismatch_count", "all_bit_exact",
                   "input_frame_mismatches", "bit_config_counts",
                   "kv_actually_quantized_frames", "tail_eviction_covered",
                   "m_quantization_exercised")}))
print("RESULT=" + RESULT)
