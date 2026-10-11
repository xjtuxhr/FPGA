#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# gen_v2_endpoint_vectors.py —— v2 endpoint 对拍（TEST echo + RESET ack）
# 协议严格按 contract.json：header <IBHBB3sIIH2sI4s，CRC-32/ISO-HDLC。
import random
import struct
import zlib

MAGIC = 0x584D564B
VERSION = 2
HDR_FMT = "<IHBBB3sIIH2sI4s"


def pack_header(op, layer, position, seq, payload_len, crc):
    return struct.pack(HDR_FMT, MAGIC, VERSION, op, 0, layer, b'\x00' * 3,
                       position, seq, payload_len, b'\x00' * 2, crc, b'\x00' * 4)


def frame_crc(header_cleared, payload):
    return zlib.crc32(header_cleared + payload) & 0xFFFFFFFF


def pack_frame(op, layer, position, seq, payload):
    h0 = pack_header(op, layer, position, seq, len(payload), 0)
    crc = frame_crc(h0, payload)
    return pack_header(op, layer, position, seq, len(payload), crc) + payload


def to_beats(b):
    return [int.from_bytes(b[i:i + 16].ljust(16, b'\x00'), 'little')
            for i in range(0, len(b), 16)]


def main():
    random.seed(5)
    cases = []
    # TEST op=2：回显前 1152B
    for (layer, position, seq) in [(3, 17, 0x01020304), (29, 2047, 0xffffffff), (0, 0, 1)]:
        pay = bytes(random.randrange(256) for _ in range(1920))
        req = pack_frame(2, layer, position, seq, pay)
        resp = pack_frame(2, layer, position, seq, pay[:1152])
        cases.append((to_beats(req), to_beats(resp)))
    # RESET_CACHE op=1：空 ack（layer=255, position=0）
    req = pack_frame(1, 255, 0, 0xdeadbeef, b'')
    resp = pack_frame(1, 255, 0, 0xdeadbeef, b'')
    cases.append((to_beats(req), to_beats(resp)))

    with open('golden/v2_endpoint.hex', 'w') as f:
        f.write(f"{len(cases):04x}\n")
        for req_b, resp_b in cases:
            f.write(f"{len(req_b):04x}\n")
            for b in req_b:
                for w in range(8):
                    f.write(f"{(b >> (16 * w)) & 0xFFFF:04x}\n")
            f.write(f"{len(resp_b):04x}\n")
            for b in resp_b:
                for w in range(8):
                    f.write(f"{(b >> (16 * w)) & 0xFFFF:04x}\n")
    print(f"generated golden/v2_endpoint.hex ({len(cases)} cases)")


if __name__ == '__main__':
    main()
