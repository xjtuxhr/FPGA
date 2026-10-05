#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_q88_fp16_vectors.py —— Q8.8 -> FP16 转换器对拍向量
# 与 Verilog q88_to_fp16.v 语义一致（round-half-away、规格化、舍入进位）。
# 输出 golden/q88_fp16.hex：首字 = case 数，之后每个 case 两字（q88, fp16）。
# ============================================================================
import random


def q88_to_fp16(q):
    q &= 0xFFFF
    if q >= 0x8000:
        q -= 0x10000
    sign = 1 if q < 0 else 0
    mag = abs(q)
    if mag == 0:
        return (sign << 15) & 0xFFFF
    L = mag.bit_length() - 1
    e = L + 7
    if L >= 10:
        if L == 10:
            sig = mag
        else:
            sig = (mag + (1 << (L - 11))) >> (L - 10)
    else:
        sig = mag << (10 - L)
    if sig == 2048:
        sig = 1024
        e += 1
    return ((sign << 15) | (e << 10) | (sig - 1024)) & 0xFFFF


def main():
    # 显式边界用例
    vals = [0, 1, -1, 2, -2, 96, -96, 128, -128, 256, -256, 384, -384,
            512, -512, 768, -768, 1024, -1024, 2048, -2048, 4096, -4096,
            8192, -8192, 16384, -16384, 32767, -32767, 32766, -32766, -32768]
    random.seed(3)
    vals += [random.randint(-32768, 32767) for _ in range(200)]

    # 自检
    assert q88_to_fp16(256) == 0x3C00          # 1.0
    assert q88_to_fp16(-256) == 0xBC00         # -1.0
    assert q88_to_fp16(128) == 0x3800          # 0.5
    assert q88_to_fp16(-32768) == 0xD800       # -128.0

    with open('golden/q88_fp16.hex', 'w') as f:
        f.write(f"{len(vals):04x}\n")
        for v in vals:
            b = v & 0xFFFF
            h = q88_to_fp16(v)
            f.write(f"{b:04x}\n{h:04x}\n")
    print(f"generated golden/q88_fp16.hex ({len(vals)} cases)")


if __name__ == '__main__':
    main()
