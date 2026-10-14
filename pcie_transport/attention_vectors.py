"""Single-layer ATTENTION request/golden helpers (PC2, standard library only).

Builds and checks the contract v2 ATTENTION frames: H2C payload is
Q[9,64] + K[3,64] + V[3,64] (FP16 LE, head-major, head_dim contiguous, order
Q then K then V) = 960 elements = 1920 B; C2H payload is output[9,64] = 576
elements = 1152 B. See pcie_contract/contract.json tensor_layout.

This module performs NO device access and NO Attention math: it only packs the
request and compares the returned tensor against a PC-provided golden. The
numeric reference belongs to PC1 (see docs/COMPUTE_ARCHITECTURE.md).

Golden JSON schema (produced on the PC reference side):

    {
      "note": "optional",
      "cases": [
        {"layer": 0, "position": 0,
         "q": [float] * 576, "k": [float] * 192, "v": [float] * 192,
         "output": [float] * 576}
      ]
    }

``output`` is optional per case: without it the runner only validates framing
(seq/layer/position/op, CRC, length) via the transport.
"""
import json
from pathlib import Path

from pcie_contract import contract as c

HIDDEN = c.HIDDEN          # 576
KV_DIM = c.KV_DIM          # 192
OUTPUT_LEN = c.HIDDEN


def _pattern_value(i: int, position: int) -> float:
    """Deterministic, small, finite FP16-safe value (no RNG)."""
    return (((i * 7 + position * 13) % 100) - 50) / 64.0


def build_pattern_qkv(position: int):
    """Return (q, k, v) float tuples for a deterministic ATTENTION request."""
    q = tuple(_pattern_value(i, position) for i in range(HIDDEN))
    k = tuple(_pattern_value(i, position + 1) for i in range(KV_DIM))
    v = tuple(_pattern_value(i, position + 2) for i in range(KV_DIM))
    return q, k, v


def pack_qkv(q, k, v) -> bytes:
    """Pack Q/K/V into the ATTENTION H2C payload (FP16 LE, Q then K then V)."""
    if len(q) != HIDDEN or len(k) != KV_DIM or len(v) != KV_DIM:
        raise ValueError(f"Q/K/V must be {HIDDEN}/{KV_DIM}/{KV_DIM}, got {len(q)}/{len(k)}/{len(v)}")
    return c.pack_f16(q) + c.pack_f16(k) + c.pack_f16(v)


def load_golden(path) -> list[dict]:
    """Load and validate a golden JSON file; returns the list of cases."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden JSON must have a non-empty 'cases' list")
    for i, case in enumerate(cases):
        for key in ("layer", "position", "q", "k", "v"):
            if key not in case:
                raise ValueError(f"golden case {i} missing '{key}'")
        if len(case["q"]) != HIDDEN or len(case["k"]) != KV_DIM or len(case["v"]) != KV_DIM:
            raise ValueError(f"golden case {i} has wrong Q/K/V lengths")
        if "output" in case and len(case["output"]) != OUTPUT_LEN:
            raise ValueError(f"golden case {i} output must be {OUTPUT_LEN} elements")
    return cases


def compare_output(response_frame: bytes, golden_output, *, atol: float = 1e-3, rtol: float = 1e-3) -> dict:
    """Compare a C2H ATTENTION frame payload against a golden output vector.

    Returns a dict with match/bad/max_abs/n and nonfinite flag. Non-finite FPGA
    output is reported (never silently scored as a match).
    """
    payload = response_frame[c.HEADER_BYTES:]
    if len(payload) != c.C2H_PAYLOAD_BYTES:
        raise ValueError(f"response payload must be {c.C2H_PAYLOAD_BYTES} bytes")
    try:
        got = c.unpack_f16(payload)
    except c.ContractError as exc:
        return {"match": False, "bad": OUTPUT_LEN, "max_abs": float("inf"),
                "n": OUTPUT_LEN, "nonfinite": True, "error": str(exc)}
    if len(golden_output) != len(got):
        raise ValueError(f"golden output length {len(golden_output)} != {len(got)}")
    bad = 0
    max_abs = 0.0
    for g, e in zip(got, golden_output):
        diff = abs(g - e)
        max_abs = max(max_abs, diff)
        if diff > atol + rtol * abs(e):
            bad += 1
    return {"match": bad == 0, "bad": bad, "max_abs": max_abs, "n": len(got), "nonfinite": False}
