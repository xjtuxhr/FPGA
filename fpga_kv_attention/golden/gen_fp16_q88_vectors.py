#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_fp16_q88_vectors.py —— FP16 -> Q8.8 转换器对拍向量
# 与 Verilog fp16_to_q88.v 语义一致（含 subnormal->0、inf/NaN 饱和、round-half-away）。
# 输出 golden/fp16_q88.hex：首字 = case 数，之后每个 case 两字（fp16, q88）。
# ============================================================================
import random
import struct


def fp16_to_q88(bits):
    s = (bits >> 15) & 1
    e = (bits >> 10) & 0x1F
    m = bits & 0x3FF
    sig = 1024 + m
    if e == 0:
        mag = 0
    elif e == 31:
        mag = 32767
    elif e >= 17:
        mag = min(sig << (e - 17), 32767)
    else:
        mag = (sig + (1 << (16 - e))) >> (17 - e)
    q = -mag if s else mag
    return q & 0xFFFF


def f16_bits(v):
    return struct.unpack('<H', struct.pack('<e', v))[0]


def main():
    # 显式边界用例
    vals = [
        0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, -2.0, 3.14159, -3.14159,
        127.0, 127.5, 127.996, 128.0, -128.0, 255.0, -255.0,
        1e-5, -1e-5, 1e-3, 0.00390625, 0.001953125, 6e-5, -6e-5,
        65504.0, -65504.0, float('inf'), float('-inf'), float('nan'),
    ]
    random.seed(1)
    vals += [random.uniform(-200, 200) for _ in range(160)]
    vals += [random.uniform(-0.02, 0.02) for _ in range(60)]

    # 自检几个已知值（1.0 -> 256，127.5 -> 32640）
    assert fp16_to_q88(f16_bits(1.0)) == 256
    assert fp16_to_q88(f16_bits(-1.0)) == (65536 - 256)
    assert fp16_to_q88(f16_bits(127.5)) == 32640
    assert fp16_to_q88(f16_bits(float('inf'))) == 32767

    with open('golden/fp16_q88.hex', 'w') as f:
        f.write(f"{len(vals):04x}\n")
        for v in vals:
            bits = f16_bits(v)
            q = fp16_to_q88(bits)
            f.write(f"{bits & 0xFFFF:04x}\n{q:04x}\n")
    print(f"generated golden/fp16_q88.hex ({len(vals)} cases)")


if __name__ == '__main__':
    main()
