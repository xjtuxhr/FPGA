#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_attention_vectors.py —— 生成 attention 集成模块对拍向量
# 与 Verilog attention.v 的定点语义完全一致（Q8.8 Q/K/V，Q16.16 score，Q0.16 prob）。
# 输出 golden/attention.hex：Q(D) + K(T×D) + V(T×D) + out(D×2, 32-bit 高低各一行)。
# ============================================================================
import math

T = 4
D = 4


def exp_val(addr):
    x = -addr / 32.0
    return max(0, min(65535, int(round(math.exp(x) * 65536))))


def attention(Q, K, V):
    scores = [sum(Q[d] * K[t][d] for d in range(D)) for t in range(T)]
    mx = max(scores)
    e = []
    for s in scores:
        neg_x = mx - s
        addr = 255 if neg_x > 522240 else (neg_x >> 11)
        e.append(exp_val(addr))
    sm = sum(e)
    p = [min(65535, (ei << 16) // sm) for ei in e]
    out = [sum(p[t] * V[t][d] for t in range(T)) for d in range(D)]
    return scores, p, out


def main():
    Q = [1024, 512, 0, -512]
    K = [[1024, 0, -1024, 0], [512, 512, 0, 0],
         [0, 0, 1024, 512], [-512, 0, 0, 1024]]
    V = [[100, 200, 300, 400], [500, 600, 700, 800],
         [900, 1000, 1100, 1200], [1300, 1400, 1500, 1600]]

    scores, p, out = attention(Q, K, V)
    print("scores:", scores)
    print("probs :", p, " sum =", sum(p))
    print("out   :", out)

    with open("golden/attention.hex", "w") as f:
        for v in Q:
            f.write(f"{v & 0xFFFF:04x}\n")
        for t in range(T):
            for d in range(D):
                f.write(f"{K[t][d] & 0xFFFF:04x}\n")
        for t in range(T):
            for d in range(D):
                f.write(f"{V[t][d] & 0xFFFF:04x}\n")
        for v in out:
            f.write(f"{(v >> 16) & 0xFFFF:04x}\n")
            f.write(f"{v & 0xFFFF:04x}\n")
    print("generated golden/attention.hex")


if __name__ == "__main__":
    main()
