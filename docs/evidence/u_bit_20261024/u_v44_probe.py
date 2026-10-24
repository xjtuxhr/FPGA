#!/usr/bin/env python3
import hashlib
import json
import os
import struct
import sys

PKG = "/home/kvdev/work_pc2_pcie/attention_pkg_20261014"
BINDING = "/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/pcie_transport/bindings/board_20261016.json"
V44 = "/home/kvdev/work_pc1_npu/full-text-v44-planb.q4RMWe"
OUT = "/home/kvdev/pcie_bringup_20261024/u_full_v44_probe_20261024"
START = 10120

sys.path.insert(0, PKG)
from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport

os.makedirs(OUT, exist_ok=True)
inp = open(V44 + "/host/.fixtures/v44_probe/attention_l0_p0.input.bin", "rb").read()
b_expected = open(V44 + "/host/.fixtures/v44_probe/attention_l0_p0.output.bin", "rb").read()
assert len(inp) == 1920 and len(b_expected) == 1152

binding = Binding.load(BINDING)
dev = SgdmaDevice(binding)
tr = Transport(dev, binding)
tr.next_seq = START
try:
    rt = tr.reset_cache(timeout_s=5.0)
    resp, timing = tr.round_trip(c.OP_ATTENTION, 0, 0, inp, timeout_s=5.0)
    _, out = c.unpack_response(resp, expect_seq=START + 1, expect_layer=0,
                               expect_position=0, expect_op=c.OP_ATTENTION)
    sh = hashlib.sha256(out).hexdigest()
    mism = sum(a != b for a, b in zip(out, b_expected))
    with open(OUT + "/attention_l0_p0.u_output.bin", "wb") as f:
        f.write(out)
    with open(OUT + "/attention_l0_p0.h2c.bin", "wb") as f:
        f.write(c.pack_request(START + 1, 0, 0, inp, op=c.OP_ATTENTION))
    with open(OUT + "/attention_l0_p0.c2h.bin", "wb") as f:
        f.write(resp)
    meta = {
        "real_date_utc": "2026-10-24",
        "bit_sha256_from_B": "B5AD8F911EC270E448993D09C1BC243B4420D873870B3B18D39BD46A2958B26B",
        "reset_seq": START, "attention_seq": START + 1,
        "input_sha256": hashlib.sha256(inp).hexdigest(),
        "u_output_sha256": sh,
        "b_expected_sha256": hashlib.sha256(b_expected).hexdigest(),
        "bytes_diff_vs_B_expected": mism,
        "reset_total_ms": rt.total_s * 1e3,
        "attention_total_ms": timing.total_s * 1e3,
    }
    with open(OUT + "/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))
finally:
    dev.close()
