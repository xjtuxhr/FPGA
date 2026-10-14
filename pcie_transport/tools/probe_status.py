"""Board-side READ-ONLY probe for the application status word (DONE/ERR).

The status word (PCIE003_INTERFACE_SPEC.md section 4) is NOT wired in the
current endpoint and its control-register offset is NOT yet defined by B. This
tool therefore NEVER guesses an address:

  * to decode one word, pass the exact ``--offset`` (and ``--method``) that B
    confirms; otherwise the tool refuses.
  * ``--dump N`` is an explicit, read-only reconnaissance scan of N 32-bit
    words from offset 0 (values are printed raw; no semantic claim), for use
    only when the operator decides a scan is safe. It never writes.

Read methods:
  pread : ``os.pread(control_fd, 4, offset)`` (spec's "4B control pread").
  iocr  : ioctl ANLOGIC_IOCR ``_IOR('x',5,struct anlogic_ioc_bar)`` with
          ``--bar`` + ``--offaddr`` (the smoke_regs mechanism).

No BAR write, no register poke, no endpoint reset. Read-only.
"""
import argparse
import os
import struct
import sys

from pcie_transport.status_word import decode

DEFAULT_NODE = "/dev/ANLOGIC-PCI0_control"


def _iocr(dir_, type_, nr, size):
    return (dir_ << 30) | (size << 16) | (type_ << 8) | nr


IOCR_R5 = _iocr(2, ord("x"), 5, 16)  # ANLOGIC_IOCR: struct anlogic_ioc_bar (16B)


def read_pread(fd, offset):
    return struct.unpack("<I", os.pread(fd, 4, offset))[0]


def read_iocr(fd, bar, offaddr):
    import fcntl  # POSIX-only; imported lazily so this module loads on Windows too
    buf = bytearray(16)
    struct.pack_into("<HHIII", buf, 0, bar, 0, offaddr, 0, 0)
    fcntl.ioctl(fd, IOCR_R5, buf, True)
    return struct.unpack_from("<I", buf, 12)[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="READ-ONLY application status-word probe (fail-closed)")
    parser.add_argument("--node", default=DEFAULT_NODE)
    parser.add_argument("--method", choices=("pread", "iocr"), default="pread")
    parser.add_argument("--offset", type=lambda s: int(s, 0), default=None,
                        help="exact 32-bit word offset for --method pread (required to decode)")
    parser.add_argument("--bar", type=lambda s: int(s, 0), default=0, help="--method iocr")
    parser.add_argument("--offaddr", type=lambda s: int(s, 0), default=None, help="--method iocr")
    parser.add_argument("--dump", type=lambda s: int(s, 0), default=0,
                        help="READ-ONLY scan of N words from offset 0 (no semantics)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.node):
        print(f"NODE_MISSING: {args.node}", file=sys.stderr)
        return 1
    fd = os.open(args.node, os.O_RDONLY)

    try:
        if args.dump > 0:
            print(f"DUMP (read-only recon, {args.dump} words from 0x0, no semantic claim):")
            for i in range(args.dump):
                off = i * 4
                try:
                    value = read_pread(fd, off) if args.method == "pread" else read_iocr(fd, args.bar, off)
                except OSError as exc:
                    print(f"  0x{off:04x}: ERR {exc}")
                    continue
                print(f"  0x{off:04x} = 0x{value:08x}")
            return 0

        if args.method == "pread" and args.offset is None:
            print("REFUSED: --offset is required (status-word offset not defined by B; no guessing). "
                  "Use --dump N for read-only recon.", file=sys.stderr)
            return 2
        if args.method == "iocr" and args.offaddr is None:
            print("REFUSED: --offaddr (and --bar) required for --method iocr.", file=sys.stderr)
            return 2

        value = read_pread(fd, args.offset) if args.method == "pread" else read_iocr(fd, args.bar, args.offaddr)
        status = decode(value)
        print(f"raw=0x{value:08x}  {status.describe()}")
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
