#!/usr/bin/env python3
"""
pcie_roundtrip.py — RK3576 <-> Anlogic FPGA SGDMA 原始往返/延迟测试 (PC2)

定位：**原始(RAW) transport 冒烟/计时**，直接读写 H2C/C2H 字符设备，
不含 v2 的 32B header/CRC/opcode。带 header 的 framed v2 OP_TEST 见
`pcie_transport/tools/run_op_test_on_board.py`。

设备节点（本板实际名称）：
    H2C: /dev/ANLOGIC-PCI0_h2c_0   (Host -> FPGA, os.write)
    C2H: /dev/ANLOGIC-PCI0_c2h_0   (FPGA -> Host, os.read)

用法示例：
    # 合同尺寸往返 + 延迟 (1920B 下发 / 1152B 回读)
    python3 pcie_roundtrip.py --mode roundtrip --h2c-size 1920 --c2h-size 1152 --iters 500

    # 只测 H2C 写
    python3 pcie_roundtrip.py --mode h2c --h2c-size 1920 --iters 1000

    # 只测 C2H 读
    python3 pcie_roundtrip.py --mode c2h --c2h-size 1152 --iters 1000

注意：
- 必须等 B 的 bitstream（回环或 attention endpoint）就绪后，roundtrip 才会回数据；
  当前摄像头 bit 下 C2H 是视频帧、H2C 无消费者，roundtrip 会 timeout（正常）。
- C2H 若无数据，用 select 超时返回，不会卡死。
"""
import os
import sys
import time
import select
import argparse
import statistics

H2C_DEV = "/dev/ANLOGIC-PCI0_h2c_0"
C2H_DEV = "/dev/ANLOGIC-PCI0_c2h_0"


def make_payload(n, pattern):
    if pattern == "seq":
        return bytes((i & 0xFF) for i in range(n))
    if pattern == "0xff":
        return b"\xff" * n
    if pattern == "0x5a":
        return b"\x5a" * n
    return bytes(n)


def read_with_timeout(fd, n, timeout):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None  # timeout
    try:
        return os.read(fd, n)
    except BlockingIOError:
        return None


def pctl(vals, p):
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["roundtrip", "h2c", "c2h"], default="roundtrip")
    ap.add_argument("--h2c-size", type=int, default=1920)
    ap.add_argument("--c2h-size", type=int, default=1152)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=1.0, help="每次读超时(秒)")
    ap.add_argument("--pattern", choices=["seq", "0xff", "0x5a", "zero"], default="seq")
    ap.add_argument("--verify", action="store_true", help="回读到与下发前 N 字节一致则计数")
    ap.add_argument("--max-err", type=int, default=3, help="读/写连续失败达到此数即提前退出")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    hfd = cfd = None
    if args.mode in ("roundtrip", "h2c"):
        hfd = os.open(H2C_DEV, os.O_WRONLY)
    if args.mode in ("roundtrip", "c2h"):
        cfd = os.open(C2H_DEV, os.O_RDONLY)

    payload = make_payload(args.h2c_size, args.pattern)
    print("mode=%s h2c_size=%d c2h_size=%d iters=%d timeout=%.2fs"
          % (args.mode, args.h2c_size, args.c2h_size, args.iters, args.timeout))

    rt, whe, rde = [], [], []
    timeouts = 0
    bytes_c2h = 0
    mismatches = 0
    werr = rerr = 0
    last_err = None
    first = None

    for it in range(args.warmup + args.iters):
        do_stat = it >= args.warmup
        t0 = time.perf_counter()
        if hfd is not None:
            tw0 = time.perf_counter()
            try:
                os.write(hfd, payload)
                tw1 = time.perf_counter()
                if do_stat:
                    whe.append((tw1 - tw0) * 1e6)
            except OSError as e:
                werr += 1
                last_err = ("h2c", e.errno)
        if cfd is not None:
            tr0 = time.perf_counter()
            try:
                data = read_with_timeout(cfd, args.c2h_size, args.timeout)
            except OSError as e:
                data = "ERR"
                rerr += 1
                last_err = ("c2h", e.errno)
            tr1 = time.perf_counter()
            if data is None:
                if do_stat:
                    timeouts += 1
            elif data == "ERR":
                pass
            else:
                bytes_c2h += len(data)
                if do_stat:
                    rde.append((tr1 - tr0) * 1e6)
                    if args.verify and len(data) >= args.c2h_size:
                        if data[:args.c2h_size] != payload[:args.c2h_size]:
                            mismatches += 1
                if first is None:
                    first = data
        t1 = time.perf_counter()
        if do_stat and hfd is not None and cfd is not None and not werr and not rerr:
            rt.append((t1 - t0) * 1e6)
        if (werr + rerr + timeouts) >= args.max_err:
            print("!! stopping early: werr=%d rerr=%d timeouts=%d (>=%d)"
                  % (werr, rerr, timeouts, args.max_err))
            break

    print("--- results ---")
    if rt:
        print("roundtrip us: P50=%.1f P90=%.1f P99=%.1f min=%.1f max=%.1f mean=%.1f"
              % (pctl(rt, 50), pctl(rt, 90), pctl(rt, 99),
                 min(rt), max(rt), statistics.mean(rt)))
    if whe:
        print("h2c-write us: P50=%.1f P99=%.1f mean=%.1f"
              % (pctl(whe, 50), pctl(whe, 99), statistics.mean(whe)))
    if rde:
        print("c2h-read  us: P50=%.1f P99=%.1f mean=%.1f"
              % (pctl(rde, 50), pctl(rde, 99), statistics.mean(rde)))
    if args.mode in ("c2h", "roundtrip"):
        print("c2h reads OK=%d timeouts=%d rerr=%d bytes=%d verify_mismatch=%d"
              % (len(rde), timeouts, rerr, bytes_c2h, mismatches))
    if args.mode in ("h2c", "roundtrip"):
        print("h2c writes OK=%d werr=%d" % (len(whe), werr))
    if last_err:
        print("last OSError: %s errno=%s" % last_err)
    if first is not None:
        print("first c2h bytes[:32]=%s" % first[:32].hex())

    if hfd is not None:
        os.close(hfd)
    if cfd is not None:
        os.close(cfd)


if __name__ == "__main__":
    main()
