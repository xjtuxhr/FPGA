#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# golden.py —— KVmix 量化/反量化 Python golden
#
# 作用：
#   1. 复现论文的非对称分组量化语义（float 参考）；
#   2. 按 Verilog 的定点格式（scale Q0.8、min Q8.8）做反量化，验证数值一致性；
#   3. 打印若干 (q, scale_int, min_int) -> x 的向量，可直接抄进 testbench 对拍。
# ============================================================================
import numpy as np

FRAC = 8   # 定点小数位（Q0.8 / Q8.8）


def quantize_group(x, qmax):
    """非对称分组量化（论文语义，float 参考）。返回 (q, scale, min)。"""
    mn = float(x.min())
    mx = float(x.max())
    scale = (mx - mn) / qmax
    if scale == 0.0:
        scale = 1.0
    q = np.clip(np.round((x - mn) / scale), 0, qmax).astype(np.int64)
    return q, scale, mn


def to_fixed(v):
    """float -> 定点整数（round 到最近）。"""
    return int(np.round(v * (1 << FRAC)))


def dequant_fixed(q, scale_int, min_int):
    """定点反量化：x = (q * scale_int + min_int) / 2^FRAC（与 kv_dequant 一致）。"""
    return (q.astype(np.float64) * scale_int + min_int) / (1 << FRAC)


def main():
    rng = np.random.default_rng(0)
    print("=== 定点反量化重建误差（1000 组，每组 32 个值）===")
    for bits in (2, 3, 4):
        qmax = (1 << bits) - 1
        errs = []
        for _ in range(1000):
            x = rng.normal(0, 1, size=32).astype(np.float32)
            q, scale, mn = quantize_group(x, qmax)
            xr = dequant_fixed(q, to_fixed(scale), to_fixed(mn))
            errs.append(np.abs(xr - x).max())
        errs = np.array(errs)
        print(f"  bits={bits}: mean_max_err={errs.mean():.4f}  max={errs.max():.4f}")

    print("\n=== 可抄进 testbench 的向量（scale Q0.8, min/x Q8.8）===")
    for q, scale, mn in [
        (3, 1.0, 0.0),
        (2, 0.5, 1.0),
        (15, 1.0, -1.0),
        (0, 100 / 256, 50 / 256),
    ]:
        scale_int = to_fixed(scale)
        min_int = to_fixed(mn)
        x_int = q * scale_int + min_int
        print(f"  q={q:>2}, scale_int={scale_int:>4}, min_int={min_int:>4} -> x_int={x_int:>5}")


if __name__ == "__main__":
    main()
