#!/usr/bin/env python3
"""
pcie_loopback.py — RAW H2C->C2H 回环确认 + 往返延迟 (PC2)

背景：B 的回环 bit 会把 H2C 收到的数据经 C2H 原样发回；但**回环 FIFO 需要边写边读**
（常驻读线程排空 C2H），否则写会因 FIFO 满而阻塞/超时。故本程序用后台读线程。

设备节点：/dev/ANLOGIC-PCI0_h2c_0 (写), /dev/ANLOGIC-PCI0_c2h_0 (读)

用法：python3 pcie_loopback.py --size 1920 --rounds 100 --pattern a5
"""
import os
import sys
import time
import select
import queue
import argparse
import statistics
import threading

H2C = "/dev/ANLOGIC-PCI0_h2c_0"
C2H = "/dev/ANLOGIC-PCI0_c2h_0"


def make_pat(size, name):
    if name == "a5":
        return bytes([0xA5]) * size
    if name == "seq":
        return bytes((i & 0xFF) for i in range(size))
    if name == "5a":
        return bytes([0x5A]) * size
    return bytes(size)


def pctl(v, p):
    s = sorted(v)
    return s[max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1920)
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--pattern", choices=["a5", "seq", "5a", "zero"], default="a5")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    pat = make_pat(args.size, args.pattern)
    h = os.open(H2C, os.O_WRONLY)
    c = os.open(C2H, os.O_RDONLY)
    q = queue.Queue()
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            r, _, _ = select.select([c], [], [], 0.2)
            if not r:
                continue
            try:
                d = os.read(c, args.size)
            except OSError:
                continue
            q.put((time.perf_counter(), d))

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.3)

    ok = bad = err = to = 0
    lat = []
    for i in range(args.warmup + args.rounds):
        measure = i >= args.warmup
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break
        try:
            time.sleep(0.002)
            t0 = time.perf_counter()
            os.write(h, pat)
        except OSError:
            err += 1
            continue
        try:
            ts, d = q.get(timeout=args.timeout)
        except queue.Empty:
            to += 1
            continue
        if len(d) == args.size and d == pat:
            ok += 1
            if measure:
                lat.append((ts - t0) * 1e6)
        else:
            bad += 1

    stop.set()
    t.join()
    os.close(h)
    os.close(c)

    print("loopback size=%d rounds=%d pattern=%s" % (args.size, args.rounds, args.pattern))
    print("OK=%d bad=%d err=%d timeout=%d" % (ok, bad, err, to))
    if lat:
        print("roundtrip us: P50=%.1f P90=%.1f P99=%.1f min=%.1f max=%.1f mean=%.1f"
              % (pctl(lat, 50), pctl(lat, 90), pctl(lat, 99),
                 min(lat), max(lat), statistics.mean(lat)))


if __name__ == "__main__":
    main()
