#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_attention_b_vectors.py —— Attention-only B 端到端对拍向量
# 数据流：FP16 Q/K/V -> fp16_to_q88（Q8.8）-> gqa_attention，与 Verilog attention_b_top 一致。
# 输出 golden/attention_b.hex：Q_fp16(H×D) + K_fp16(G×T×D) + V_fp16(G×T×D) + out(H×D×2)。
# ============================================================================
import math
import random
import struct

H, G, D, T = 9, 3, 64, 64
NGROUPS = H // G


def trunc32(x):
    x &= 0xFFFFFFFF
    if x >= 0x80000000:
        x -= 0x100000000
    return x


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
    q &= 0xFFFF
    return q - 0x10000 if q >= 0x8000 else q   # 有符号 Q8.8（供 attention 算术用）


def f16_bits(v):
    return struct.unpack('<H', struct.pack('<e', v))[0]


def exp_val(addr):
    x = -addr / 32.0
    return max(0, min(65535, int(round(math.exp(x) * 65536))))


def attention(Q, K, V):
    score_ideal = [sum(Q[d] * K[t][d] for d in range(D)) for t in range(T)]
    scores = [trunc32(s) for s in score_ideal]
    mx = max(scores)
    e = []
    for s in scores:
        neg_x = mx - s
        addr = 255 if neg_x > 522240 else (neg_x >> 11)
        e.append(exp_val(addr))
    sm = sum(e)
    p = [min(65535, (ei << 16) // sm) for ei in e]
    out = [trunc32(sum(p[t] * V[t][d] for t in range(T))) for d in range(D)]
    return out


def main():
    random.seed(2)
    # 归一化后的 Q/K/V 量级（值 ±2.0 以内，Q8.8 内不饱和），含少量大值压饱和路径
    def rnd():
        return random.uniform(-2.0, 2.0) if random.random() < 0.9 \
            else random.uniform(-150.0, 150.0)

    Qf = [[rnd() for _ in range(D)] for _ in range(H)]
    Kf = [[[rnd() for _ in range(D)] for _ in range(T)] for _ in range(G)]
    Vf = [[[rnd() for _ in range(D)] for _ in range(T)] for _ in range(G)]

    # 转 Q8.8（与 fp16_to_q88 一致）
    Q = [[fp16_to_q88(f16_bits(Qf[h][d])) for d in range(D)] for h in range(H)]
    K = [[[fp16_to_q88(f16_bits(Kf[g][t][d])) for d in range(D)] for t in range(T)]
         for g in range(G)]
    V = [[[fp16_to_q88(f16_bits(Vf[g][t][d])) for d in range(D)] for t in range(T)]
         for g in range(G)]

    outs = []
    for h in range(H):
        g = h // NGROUPS
        outs.append(attention(Q[h], K[g], V[g]))

    with open('golden/attention_b.hex', 'w') as f:
        for h in range(H):
            for d in range(D):
                f.write(f"{f16_bits(Qf[h][d]) & 0xFFFF:04x}\n")
        for g in range(G):
            for t in range(T):
                for d in range(D):
                    f.write(f"{f16_bits(Kf[g][t][d]) & 0xFFFF:04x}\n")
        for g in range(G):
            for t in range(T):
                for d in range(D):
                    f.write(f"{f16_bits(Vf[g][t][d]) & 0xFFFF:04x}\n")
        for h in range(H):
            for d in range(D):
                v = outs[h][d]
                f.write(f"{(v >> 16) & 0xFFFF:04x}\n")
                f.write(f"{v & 0xFFFF:04x}\n")
    print(f"generated golden/attention_b.hex (H={H} G={G} D={D} T={T})")


if __name__ == '__main__':
    main()
