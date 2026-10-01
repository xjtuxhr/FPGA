"""Single-inflight PCIe transport state machine (logical states only).

Implements the v2 README section 7 flow over a DeviceOps backend. This file
defines LOGICAL states, not hardware registers; how H2C/C2H/notification map
to real SGDMA nodes is filled in by the binding evidence. Until then the
transport refuses to run (UNBOUND guard).

Guarantees:
- at most one request in flight; the request slot is occupied BEFORE the
  first device call, so concurrent/reentrant calls are rejected immediately
- Attention is refused until a valid RESET_CACHE ACK was received
  (recover() re-arms this requirement; KV state is otherwise uncertain)
- seq strictly increases, never reused; stale frames/old DONE never satisfy
  a new request
- every request has ONE finite monotonic deadline covering the whole
  request; inf/nan timeouts are rejected
- short write/read is not completion; no silent retry, no KV re-append
- after H2C write the device is explicitly notified (logical doorbell);
  how that maps to hardware is defined by the binding
- any protocol/device error -> FAULT; caller misuse (reentrancy) raises
  without corrupting the in-flight request
"""
from dataclasses import dataclass
from enum import Enum
import math
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
        if not isinstance(binding, Binding) or not binding.is_bound:
            raise BindingError("Transport refuses to run without complete binding evidence")
        binding.validate()
        self.device = device
        self.binding = binding
        self.state = State.IDLE
        self.next_seq = 1
        self.inflight: tuple[int, int, int, int] | None = None  # (seq, op, layer, position)
        self.needs_reset = True

    def _deadline(self, timeout_s: float) -> float:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise TransportError("Timeout must be finite and positive (one deadline per request)")
        return time.monotonic() + timeout_s

    def _enter_fault(self, exc: Exception) -> None:
        previous = self.state
        self.state = State.FAULT
        raise TransportError(f"Transport FAULT (was {previous.value}): {exc}") from exc

    def _check_recoverable(self) -> None:
        if self.state is State.FAULT:
            raise TransportError("Transport is in FAULT; both sides must re-confirm and reset")

    def _occupy(self, seq: int, op: int, layer: int, position: int) -> None:
        """Claim the single request slot BEFORE any device call.

        Reentrant/concurrent misuse raises without entering FAULT: the
        legitimate in-flight request must not be corrupted.
        """
        if self.state is not State.IDLE or self.inflight is not None:
            raise TransportError("Request already in flight; single-inflight protocol violated")
        self.state = State.H2C_SUBMITTED
        self.inflight = (seq, op, layer, position)

    def _release(self) -> None:
        self.state = State.IDLE
        self.inflight = None

    def _write_checked(self, frame: bytes, deadline: float) -> None:
        written = self.device.write(frame, deadline=deadline)
        if written != len(frame):
            raise TransportError(f"Short write: {written}/{len(frame)} bytes; no fragmentation retry")
        self.device.notify()

    def recover(self) -> None:
        """Explicit recovery after FAULT: isolate stale queues, re-arm reset.

        Requires both sides to have confirmed the failure. After recovery,
        Attention stays blocked until a valid reset ACK; seq never rewinds
        inside a session.
        """
        self.device.flush_queues()
        self.state = State.IDLE
        self.inflight = None
        self.needs_reset = True

    def reset_cache(self, *, timeout_s: float = 5.0) -> RoundTiming:
        self._check_recoverable()
        if self.state is not State.IDLE or self.inflight is not None:
            raise TransportError("reset_cache requires IDLE with no request in flight")
        seq = self.next_seq
        self.next_seq += 1
        frame = c.pack_reset(seq)
        deadline = self._deadline(timeout_s)
        self._occupy(seq, c.OP_RESET_CACHE, c.GLOBAL_LAYER, 0)
        t0 = time.monotonic()
        try:
            self._write_checked(frame, deadline)
            ready = self.device.wait_ready(seq, deadline=deadline)
            if not ready:
                raise TransportError("wait_ready deadline expired")
            self.state = State.WAITING
            ack = self.device.read_exact(c.HEADER_BYTES, deadline=deadline)
            self.state = State.READBACK
            c.unpack_reset_response(ack, expect_seq=seq)
            self.needs_reset = False
            self.state = State.CONSUMED
        except Exception as exc:
            self._enter_fault(exc)
        t1 = time.monotonic()
        self._release()
        return RoundTiming(t1 - t0, 0.0, 0.0, 0.0)

    def round_trip(self, op: int, layer: int, position: int, payload: bytes, *,
                   timeout_s: float = 5.0) -> tuple[bytes, RoundTiming]:
        """One framed H2C request -> C2H response with full verification.

        timeout_s is the budget for the WHOLE request (one deadline shared by
        write, wait, readback); not a per-stage value.
        """
        self._check_recoverable()
        if op not in (c.OP_ATTENTION, c.OP_TEST):
            raise TransportError(f"round_trip does not handle op {op}; use reset_cache()")
        if op == c.OP_ATTENTION and self.needs_reset:
            raise TransportError("Attention refused: a valid reset ACK is required first")
        seq = self.next_seq
        self.next_seq += 1
        frame = c.pack_request(seq, layer, position, payload, op=op)
        expected_size = c.HEADER_BYTES + c.C2H_PAYLOAD_BYTES
        deadline = self._deadline(timeout_s)
        self._occupy(seq, op, layer, position)
        timing: dict[str, float] = {}
        try:
            t0 = time.monotonic()
            self._write_checked(frame, deadline)
            timing["submit_s"] = time.monotonic() - t0
            t0 = time.monotonic()
            ready = self.device.wait_ready(seq, deadline=deadline)
            if not ready:
                raise TransportError("wait_ready deadline expired")
            timing["wait_s"] = time.monotonic() - t0
            self.state = State.WAITING
            t0 = time.monotonic()
            response = self.device.read_exact(expected_size, deadline=deadline)
            timing["readback_s"] = time.monotonic() - t0
            self.state = State.READBACK
            t0 = time.monotonic()
            c.unpack_response(response, expect_seq=seq, expect_layer=layer,
                              expect_position=position, expect_op=op)
            timing["verify_s"] = time.monotonic() - t0
            self.state = State.CONSUMED
        except Exception as exc:
            self._enter_fault(exc)
        self._release()
        return response, RoundTiming(timing["submit_s"], timing["wait_s"],
                                     timing["readback_s"], timing["verify_s"])
