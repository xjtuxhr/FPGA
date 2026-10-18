"""Status-aware B-mode session builder and 30-round OP_TEST runner.

This is a PC2 integration layer: it wires the existing PC2 Transport/SgdmaDevice
to the draft READY/FAULT/DONE + SOFT_RESET adapter. It refuses to guess the
status/control offsets until B confirms them.

No hard-deadline claim: deadline_enforced stays whatever the inner device says
(False on the current driver). The AbortableDevice wrapper only adds a
best-effort in-flight abort at the request deadline.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from pcie_contract import contract as codec
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import Transport

from status_adapter import AbortableDevice, RealBarStatus, SgdmaAbort, StatusTransport


@dataclass(frozen=True)
class StatusConfig:
    bar_id: int | None = None
    status_offset: int | None = None
    control_offset: int | None = None
    node: str | None = None
    use_ioctl: bool = False
    abort_node: str = "/dev/ANLOGIC-PCI0_h2c_0"
    ready_timeout_s: float = 1.0
    request_timeout_s: float = 5.0
    abort_grace_s: float = 5.0

    @classmethod
    def load(cls, path: Path) -> "StatusConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls(**data)

    def validate(self) -> None:
        if self.bar_id not in (0, 1):
            raise ValueError("bar_id must be 0 (user/BAR0) or 1 (control/BAR1)")
        for name in ("status_offset", "control_offset"):
            value = getattr(self, name)
            if value is None:
                raise ValueError(name + " is not frozen; B must confirm the free offset")
            if type(value) is not int or value < 0 or value & 3:
                raise ValueError(name + " must be a non-negative 4-byte aligned int")
        if self.ready_timeout_s <= 0 or self.request_timeout_s <= 0 or self.abort_grace_s <= 0:
            raise ValueError("timeouts must be positive")


class StatusSession:
    def __init__(self, transport: Transport, device, status, config: StatusConfig):
        self.transport = transport
        self.device = device
        self.status = status
        self.config = config

    @property
    def deadline_enforced(self) -> bool:
        return bool(getattr(self.device, "deadline_enforced", False))

    def close(self) -> None:
        self.device.close()

    def read_status(self) -> int:
        return self.status.read_status()


def build_real_session(config: StatusConfig, *, binding_path: Path) -> StatusSession:
    config.validate()
    binding = Binding.load(binding_path)
    status = RealBarStatus(
        bar_id=config.bar_id,
        status_offset=config.status_offset,
        control_offset=config.control_offset,
        node=config.node,
        use_ioctl=config.use_ioctl,
    )
    inner = SgdmaDevice(binding)
    wrapped = StatusTransport(inner, status)
    device = AbortableDevice(
        wrapped,
        abort_fn=SgdmaAbort(config.abort_node),
        abort_grace_s=config.abort_grace_s,
    )
    transport = Transport(device, binding)
    return StatusSession(transport, device, status, config)


def run_op_test(session: StatusSession, *, start_seq: int, rounds: int,
                timeout_s: float | None = None) -> list[dict]:
    if type(start_seq) is not int or start_seq <= 0:
        raise ValueError("start_seq must be a positive int")
    if type(rounds) is not int or rounds < 0:
        raise ValueError("rounds must be a non-negative int")
    timeout = session.config.request_timeout_s if timeout_s is None else timeout_s
    transport = session.transport
    transport.next_seq = start_seq
    results = []
    reset = transport.reset_cache(timeout_s=timeout)
    results.append({"op": "RESET_CACHE", "total_s": reset.total_s})
    for _ in range(rounds):
        seq = transport.next_seq
        payload = codec.make_test_payload(seq)
        frame, timing = transport.round_trip(
            codec.OP_TEST, 0, 0, payload, timeout_s=timeout
        )
        _, output = codec.unpack_response(
            frame, expect_seq=seq, expect_op=codec.OP_TEST,
            expect_layer=0, expect_position=0,
        )
        expected = payload[:codec.C2H_PAYLOAD_BYTES]
        if output != expected:
            raise RuntimeError("TEST byte mismatch at seq %d" % seq)
        results.append({
            "op": "TEST", "seq": seq, "total_s": timing.total_s,
            "bit_exact": True,
        })
    return results


def probe_status(config: StatusConfig) -> int:
    config.validate()
    status = RealBarStatus(
        bar_id=config.bar_id,
        status_offset=config.status_offset,
        control_offset=config.control_offset,
        node=config.node,
        use_ioctl=config.use_ioctl,
    )
    try:
        value = status.read_status()
    finally:
        status.close()
    print("STATUS=0x%08x" % value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--start-seq", type=int)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--probe-only", action="store_true",
                        help="read STATUS only; does not send H2C")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate config only; do not touch devices")
    args = parser.parse_args()

    config = StatusConfig.load(args.config)
    if args.dry_run:
        config.validate()
        print("CONFIG_OK bar_id=%d status=0x%x control=0x%x node=%s" % (
            config.bar_id, config.status_offset, config.control_offset,
            config.node or "auto"))
        return 0

    if args.probe_only:
        probe_status(config)
        return 0

    if not args.binding:
        parser.error("--binding is required unless --probe-only/--dry-run")
    if args.start_seq is None:
        parser.error("--start-seq is required")
    session = build_real_session(config, binding_path=args.binding)
    try:
        results = run_op_test(session, start_seq=args.start_seq,
                              rounds=args.rounds, timeout_s=args.timeout)
    finally:
        session.close()
    for row in results:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
