#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_vectors.py —— 生成软硬件对拍的定点测试向量
#
# 与 Verilog kv_quant / kv_dequant 的定点语义完全一致：
#   定点格式：x/min Q8.8 有符号，scale/inv_scale Q0.8 无符号（值 = int/256）
#   量化：  q = clamp(floor((diff*inv_scale + 2^15) / 2^16), 0, QMAX)
#   反量化：x_recon = q*scale + min（取低 16 位）
#
# 输出：
#   golden/quant.hex   每行 64-bit：{q[4], inv_scale[16], min[16], x[16]}（高到低）
#   golden/dequant.hex 每行 64-bit：{x_recon[16], min[16], scale[16], q[4]}（高到低）
# ============================================================================
import numpy as np

FRAC = 8
Q_BITS = 4
QMAX = (1 << Q_BITS) - 1
N = 2000


def main():
    rng = np.random.default_rng(42)
    quant_lines = []
    dequant_lines = []

    for _ in range(N):
        # 随机一个量化组：min、span(=max-min)、scale、inv_scale
        mn = float(rng.uniform(-3.0, 1.0))
        span = float(rng.uniform(0.5, 5.0))
        scale = span / QMAX
        inv_scale = QMAX / span

        # 随机 x，略微越界以测上下截位
        x = float(rng.uniform(mn - 0.2 * span, mn + span + 0.2 * span))

        # 定点转换
        x_int = int(round(x * (1 << FRAC)))
        mn_int = int(round(mn * (1 << FRAC)))
        inv_int = int(round(inv_scale * (1 << FRAC)))
        scale_int = int(round(scale * (1 << FRAC)))

        # 定点量化（与 kv_quant 完全一致）
        diff = x_int - mn_int
        rnd = diff * inv_int + (1 << 15)
        q = rnd // (1 << 16)          # floor 除法，等价 Verilog >>>16
        q = max(0, min(QMAX, q))

        # 定点反量化（与 kv_dequant 完全一致，取低 16 位）
        x_recon = (q * scale_int + mn_int) & 0xFFFF

        qw = (q << 48) | ((inv_int & 0xFFFF) << 32) | ((mn_int & 0xFFFF) << 16) | (x_int & 0xFFFF)
        dw = ((x_recon & 0xFFFF) << 36) | ((mn_int & 0xFFFF) << 20) | ((scale_int & 0xFFFF) << 4) | (q & 0xF)

        quant_lines.append(f"{qw:016x}")
        dequant_lines.append(f"{dw:016x}")

    with open("golden/quant.hex", "w") as f:
        f.write("\n".join(quant_lines) + "\n")
    with open("golden/dequant.hex", "w") as f:
        f.write("\n".join(dequant_lines) + "\n")
    print(f"generated {N} vectors -> golden/quant.hex, golden/dequant.hex")


if __name__ == "__main__":
    main()
