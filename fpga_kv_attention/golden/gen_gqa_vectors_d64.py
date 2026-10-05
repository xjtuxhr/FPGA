#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_gqa_vectors_d64.py —— GQA attention 真实尺寸（SmolLM H=9/G=3/D=64）对拍向量
# 与 Verilog gqa_attention.v / attention.v 的定点语义一致，包括：
#   - score 累加器 40-bit -> scores[] 截断到 32-bit（两补码回绕）
#   - out 累加器 32-bit 截断
# 输出 golden/gqa_d64.hex：Q(H×D) + K(G×T×D) + V(G×T×D) + out(H×D×2)。
# 同时打印「理想（不截断）」的 max|score| / max|out|，用于 NUM-002 溢出边界分析。
# ============================================================================
import argparse
import math
import random


def trunc32(x):
    """两补码 32-bit 截断（与 Verilog 赋值到 32-bit reg 一致）"""
    x &= 0xFFFFFFFF
    if x >= 0x80000000:
        x -= 0x100000000
    return x


def exp_val(addr):
    x = -addr / 32.0
    return max(0, min(65535, int(round(math.exp(x) * 65536))))


def attention(Q, K, V, D, T):
    # 理想（满精度）score，与 Verilog 40-bit acc 一致
    score_ideal = [sum(Q[d] * K[t][d] for d in range(D)) for t in range(T)]
    # Verilog 把 40-bit acc 存进 32-bit scores[]
    scores = [trunc32(s) for s in score_ideal]

    mx = max(scores)
    e = []
    for s in scores:
        neg_x = mx - s
        addr = 255 if neg_x > 522240 else (neg_x >> 11)
        e.append(exp_val(addr))
    sm = sum(e)
    p = [min(65535, (ei << 16) // sm) for ei in e]

    # 理想 out（满精度）与 Verilog 32-bit out_acc 截断
    out_ideal = [sum(p[t] * V[t][d] for t in range(T)) for d in range(D)]
    out = [trunc32(o) for o in out_ideal]
    return out, score_ideal, out_ideal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--h', type=int, default=9)
    ap.add_argument('--g', type=int, default=3)
    ap.add_argument('--d', type=int, default=64)
    ap.add_argument('--t', type=int, default=64)
    ap.add_argument('--range', type=int, default=512, help='Q/K/V Q8.8 int 幅值 ±')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out', default='golden/gqa_d64.hex')
    a = ap.parse_args()

    H, G, D, T = a.h, a.g, a.d, a.t
    NGROUPS = H // G
    random.seed(a.seed)

    Q = [[random.randint(-a.range, a.range) for _ in range(D)] for _ in range(H)]
    K = [[[random.randint(-a.range, a.range) for _ in range(D)] for _ in range(T)]
         for _ in range(G)]
    V = [[[random.randint(-a.range, a.range) for _ in range(D)] for _ in range(T)]
         for _ in range(G)]

    outs = []
    max_score_ideal = 0
    max_out_ideal = 0
    for h in range(H):
        g = h // NGROUPS
        o, si, oi = attention(Q[h], K[g], V[g], D, T)
        outs.append(o)
        max_score_ideal = max(max_score_ideal, max(abs(x) for x in si))
        max_out_ideal = max(max_out_ideal, max(abs(x) for x in oi))

    lim = (1 << 31) - 1
    print(f"H={H} G={G} D={D} T={T} range=±{a.range}")
    print(f"  max|score| ideal = {max_score_ideal:>12d}  (limit {lim}, overflow={max_score_ideal > lim})")
    print(f"  max|out|   ideal = {max_out_ideal:>12d}  (limit {lim}, overflow={max_out_ideal > lim})")
    print(f"  worst-case bound: score <={D}*range^2={D * a.range * a.range}, "
          f"out <={65536}*range={65536 * a.range}")

    with open(a.out, 'w') as f:
        for h in range(H):
            for d in range(D):
                f.write(f"{Q[h][d] & 0xFFFF:04x}\n")
        for g in range(G):
            for t in range(T):
                for d in range(D):
                    f.write(f"{K[g][t][d] & 0xFFFF:04x}\n")
        for g in range(G):
            for t in range(T):
                for d in range(D):
                    f.write(f"{V[g][t][d] & 0xFFFF:04x}\n")
        for h in range(H):
            for d in range(D):
                v = outs[h][d]
                f.write(f"{(v >> 16) & 0xFFFF:04x}\n")
                f.write(f"{v & 0xFFFF:04x}\n")
    print(f"generated {a.out}")


if __name__ == '__main__':
    main()
