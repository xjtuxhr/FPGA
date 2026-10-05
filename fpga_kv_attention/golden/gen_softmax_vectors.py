#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_softmax_vectors.py —— 生成 softmax 对拍向量
# 与 Verilog softmax 的定点语义完全一致（Q8.8 score，Q0.16 prob，exp LUT 相同）。
# 输出 golden/softmax.hex：每个 case = T 个 score + T 个期望 p（各 16-bit 十六进制）。
# ============================================================================
import math
import random

T = 4
N_CASES = 8


def exp_val(addr):
    x = -addr / 32.0
    return max(0, min(65535, int(round(math.exp(x) * 65536))))


def softmax_fixed(scores):
    mx = max(scores)
    e = []
    for s in scores:
        neg_x = mx - s
        addr = 255 if neg_x > 2040 else (neg_x >> 3)
        e.append(exp_val(addr))
    sm = sum(e)
    p = []
    for ei in e:
        p.append(min(65535, (ei << 16) // sm))
    return p


def main():
    random.seed(3)
    cases = []
    for _ in range(N_CASES):
        scores = [random.randint(-2000, 2000) for _ in range(T)]
        p = softmax_fixed(scores)
        cases.append((scores, p))

    with open("golden/softmax.hex", "w") as f:
        for scores, p in cases:
            for s in scores:
                f.write(f"{s & 0xFFFF:04x}\n")
            for pi in p:
                f.write(f"{pi & 0xFFFF:04x}\n")

    scores, p = cases[0]
    print("case0 scores:", scores)
    print("case0 p     :", p, " sum =", sum(p))
    print(f"generated {N_CASES} cases -> golden/softmax.hex")


if __name__ == "__main__":
    main()
