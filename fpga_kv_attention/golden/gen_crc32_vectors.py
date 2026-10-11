#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# gen_crc32_vectors.py —— CRC-32/ISO-HDLC 对拍向量（zlib.crc32 参考）
# 输出 golden/crc32.hex：首字 = case 数；每 case = beats 数 + beats（每拍 8×16bit 字）+ crc（2×16bit 字）
import random
import zlib

def main():
    assert zlib.crc32(b"123456789") == 0xCBF43926, "zlib mismatch"
    random.seed(7)
    cases = [b"123456789" + bytes(7)]           # 16 字节，含 check 前缀
    cases += [bytes(random.randrange(256) for _ in range(16 * random.randint(1, 8)))
              for _ in range(8)]
    with open('golden/crc32.hex', 'w') as f:
        f.write(f"{len(cases):04x}\n")
        for c in cases:
            n_beats = len(c) // 16
            crc = zlib.crc32(c) & 0xFFFFFFFF
            f.write(f"{n_beats:04x}\n")
            for i in range(n_beats):
                beat = int.from_bytes(c[i*16:(i+1)*16], 'little')
                for w in range(8):
                    f.write(f"{(beat >> (16*w)) & 0xFFFF:04x}\n")
            f.write(f"{crc & 0xFFFF:04x}\n{(crc >> 16) & 0xFFFF:04x}\n")
    print(f"generated golden/crc32.hex ({len(cases)} cases)")

if __name__ == '__main__':
    main()
