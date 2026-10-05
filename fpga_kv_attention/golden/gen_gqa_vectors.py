#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_gqa_vectors.py —— 生成 GQA 头复用模块对拍向量
# 与 Verilog gqa_attention.v 的定点语义一致。
# 输出 golden/gqa.hex：Q(H×D) + K(G×T×D) + V(G×T×D) + out(H×D×2, 32-bit)。
# ============================================================================
import math

H, G, D, T = 4, 2, 4, 4
NGROUPS = H // G


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
    return out


def main():
    # 固定数据（便于核对）
    Q = [[1024, 512, 0, -512], [256, 256, 256, 256], [-512, 0, 512, 1024], [768, -256, 512, -768]]
    K = [
        [[1024, 0, -1024, 0], [512, 512, 0, 0], [0, 0, 1024, 512], [-512, 0, 0, 1024]],
        [[256, -256, 256, -256], [0, 512, 0, -512], [1024, 0, 0, 0], [0, 0, -512, 512]],
    ]
    V = [
        [[100, 200, 300, 400], [500, 600, 700, 800], [900, 1000, 1100, 1200], [1300, 1400, 1500, 1600]],
        [[-100, 200, -300, 400], [-500, 600, -700, 800], [900, -1000, 1100, -1200], [1300, -1400, 1500, -1600]],
    ]

    outs = []
    for h in range(H):
        g = h // NGROUPS
        outs.append(attention(Q[h], K[g], V[g]))

    print("gqa outputs:")
    for h in range(H):
        print(f"  head {h} (KV {h // NGROUPS}): {outs[h]}")

    with open("golden/gqa.hex", "w") as f:
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
    print("generated golden/gqa.hex")


if __name__ == "__main__":
    main()
