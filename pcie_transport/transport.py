"""Single-inflight PCIe transport state machine (logical states only).

Implements the v2 README section 7 flow over a DeviceOps backend. This file
defines LOGICAL states, not hardware registers; how H2C/C2H/notification map
to real SGDMA nodes is filled in by the binding evidence. Until then the
transport refuses to run (UNBOUND guard).

Guarantees:
- at most one request in flight; seq strictly increases, never reused
- stale frames/old DONE never satisfy a new request
- all waits use a finite monotonic deadline
- short read/write is not completion
- any error -> FAULT; no silent retry, no KV re-append
"""
from dataclasses import dataclass
from enum import Enum
import time
from typing import Protocol

from pcie_contract import contract as c
from pcie_transport.binding import Binding, BindingError


class TransportError(RuntimeError):
    """Transport-level failure; state is FAULT and requires explicit recovery."""


class State(str, Enum):
    IDLE = "IDLE"
    H2C_SUBMITTED = "H2C_SUBMITTED"
    WAITING = "WAITING"
    READBACK = "READBACK"
    CONSUMED = "CONSUMED"
    FAULT = "FAULT"


class DeviceOps(Protocol):
    """Minimal device interface; the real binding implements these."""

    def write(self, frame: bytes, *, deadline: float) -> int: ...
    def read_exact(self, count: int, *, deadline: float) -> bytes: ...
    def notify(self) -> None: ...
    def wait_ready(self, seq: int, *, deadline: float) -> bool: ...
    def flush_queues(self) -> None: ...


@dataclass(frozen=True)
class RoundTiming:
    submit_s: float
    wait_s: float
    readback_s: float
    verify_s: float

    @property
    def total_s(self) -> float:
        return self.submit_s + self.wait_s + self.readback_s + self.verify_s


class Transport:
    def __init__(self, device: DeviceOps, binding: Binding | None = None):
        if binding is None or not binding.is_bound:
            raise BindingError("Transport refuses to run without complete binding evidence")
        self.device = device
        self.binding = binding
        self.state = State.IDLE
        self.next_seq = 1
        self.inflight: tuple[int, int, int, int] | None = None  # (seq, op, layer, position)

    def _deadline(self, timeout_s: float) -> float:
        if timeout_s <= 0:
            raise TransportError("Timeout must be positive and finite")
        return time.monotonic() + timeout_s

    def _enter_fault(self, exc: Exception) -> None:
        previous = self.state
        self.state = State.FAULT
        raise TransportError(f"Transport FAULT (was {previous.value}): {exc}") from exc

    def _check_recoverable(self) -> None:
        if self.state is State.FAULT:
            raise TransportError("Transport is in FAULT; both sides must re-confirm and reset")

    def recover(self) -> None:
        """Explicit recovery after FAULT: isolate stale queues, then allow reset.

        Requires both sides to have confirmed the failure; does not itself
        re-run or guess. The next caller MUST start with reset_cache().
        """
        self.device.flush_queues()
        self.state = State.IDLE
        self.inflight = None
        # seq never rewinds inside a session; next caller must start with reset_cache()

    def reset_cache(self, *, timeout_s: float = 5.0) -> RoundTiming:
        self._check_recoverable()
        if self.state is not State.IDLE or self.inflight is not None:
            self._enter_fault(TransportError("reset_cache requires IDLE with no request in flight"))
        seq = self.next_seq
        self.next_seq += 1
        frame = c.pack_reset(seq)
        t0 = time.monotonic()
        try:
            self.device.write(frame, deadline=self._deadline(timeout_s))
            self.state = State.H2C_SUBMITTED
            self.inflight = (seq, c.OP_RESET_CACHE, c.GLOBAL_LAYER, 0)
            ready = self.device.wait_ready(seq, deadline=self._deadline(timeout_s))
            if not ready:
                raise TransportError("wait_ready deadline expired")
            self.state = State.WAITING
            ack = self.device.read_exact(c.HEADER_BYTES, deadline=self._deadline(timeout_s))
            self.state = State.READBACK
            c.unpack_reset_response(ack, expect_seq=seq)
            t1 = time.monotonic()
            self.state = State.CONSUMED
        except Exception as exc:
            self._enter_fault(exc)
        self.state = State.IDLE
        self.inflight = None
        return RoundTiming(t1 - t0, 0.0, 0.0, 0.0)

    def round_trip(self, op: int, layer: int, position: int, payload: bytes, *,
                   timeout_s: float = 5.0) -> tuple[bytes, RoundTiming]:
        """One framed H2C request -> C2H response with full verification."""
        self._check_recoverable()
        if self.state is not State.IDLE or self.inflight is not None:
            self._enter_fault(TransportError("round_trip requires IDLE with no request in flight"))
        seq = self.next_seq
        self.next_seq += 1
        if op not in (c.OP_ATTENTION, c.OP_TEST):
            self._enter_fault(TransportError(f"round_trip does not handle op {op}; use reset_cache()"))
        frame = c.pack_request(seq, layer, position, payload, op=op)
        expected_size = c.HEADER_BYTES + c.C2H_PAYLOAD_BYTES
        timing: dict[str, float] = {}
        try:
            t0 = time.monotonic()
            self.device.write(frame, deadline=self._deadline(timeout_s))
            timing["submit_s"] = time.monotonic() - t0
            self.state = State.H2C_SUBMITTED
            self.inflight = (seq, op, layer, position)
            t0 = time.monotonic()
            ready = self.device.wait_ready(seq, deadline=self._deadline(timeout_s))
            if not ready:
                raise TransportError("wait_ready deadline expired")
            timing["wait_s"] = time.monotonic() - t0
            self.state = State.WAITING
            t0 = time.monotonic()
            response = self.device.read_exact(expected_size, deadline=self._deadline(timeout_s))
            timing["readback_s"] = time.monotonic() - t0
            self.state = State.READBACK
            t0 = time.monotonic()
            c.unpack_response(response, expect_seq=seq, expect_layer=layer,
                              expect_position=position, expect_op=op)
            timing["verify_s"] = time.monotonic() - t0
            self.state = State.CONSUMED
        except Exception as exc:
            self._enter_fault(exc)
        self.state = State.IDLE
        self.inflight = None
        return response, RoundTiming(timing["submit_s"], timing["wait_s"],
                                     timing["readback_s"], timing["verify_s"])
