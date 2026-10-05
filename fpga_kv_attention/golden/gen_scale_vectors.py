#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_scale_vectors.py —— 生成 scale 计算的定点测试向量
#
# 与 Verilog scale_calc 一致：inv_scale = floor((qmax << 16) / span)，span = max-min
# 输出 golden/scale.hex：每行 64-bit = {inv_scale[16], min[16], max[16]}（高到低）
# ============================================================================
import numpy as np

Q_BITS = 4
QMAX = (1 << Q_BITS) - 1
N = 1000


def main():
    rng = np.random.default_rng(7)
    lines = []
    for _ in range(N):
        mn = float(rng.uniform(-3.0, 1.0))
        span = float(rng.uniform(0.25, 6.0))    # 保证 span_int >= 64，商在 16 位内
        mx = mn + span
        mn_int = int(round(mn * 256))
        mx_int = int(round(mx * 256))
        span_int = mx_int - mn_int
        if span_int <= 0:
            span_int = 64
        inv = (QMAX << 16) // span_int          # floor，与除法器一致
        inv &= 0xFFFF
        word = (inv << 32) | ((mn_int & 0xFFFF) << 16) | (mx_int & 0xFFFF)
        lines.append(f"{word:016x}")

    with open("golden/scale.hex", "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"generated {N} scale vectors -> golden/scale.hex")


if __name__ == "__main__":
    main()
