import hashlib
import json
import os

GOLD = "/home/kvdev/pcie_bringup_20261024/pc_20261024_u_t2_256_golden.json"
OUT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024/outputs"
RESULT = "/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024/u_t2_256_golden_compare.json"

gold = json.load(open(GOLD, encoding="utf-8"))
rows = gold["rows"]
if len(rows) != 256:
    raise SystemExit("expected 256 golden rows, got %d" % len(rows))
mismatches = []
concat = hashlib.sha256()
for row in rows:
    pos = row["position"]
    data = open(os.path.join(OUT, "pos%03d.bin" % pos), "rb").read()
    h = hashlib.sha256(data).hexdigest()
    concat.update(data)
    if h != row["output_sha256"]:
        mismatches.append({"position": pos, "board_sha256": h,
                           "golden_sha256": row["output_sha256"]})
result = {
    "golden_file": GOLD,
    "golden_status": gold.get("status"),
    "golden_concatenated_output_sha256": gold.get("concatenated_output_sha256"),
    "board_concatenated_output_sha256": concat.hexdigest(),
    "positions_compared": len(rows),
    "mismatch_count": len(mismatches),
    "mismatches": mismatches,
    "status": "PASS_U_T2_256_GOLDEN_BIT_EXACT" if not mismatches else "FAIL_U_T2_256_GOLDEN",
}
with open(RESULT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: result[k] for k in
                  ("status", "positions_compared", "mismatch_count",
                   "golden_concatenated_output_sha256",
                   "board_concatenated_output_sha256")}))
print("RESULT=" + RESULT)
