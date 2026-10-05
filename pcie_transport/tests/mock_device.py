"""In-memory device for transport tests. Not board evidence.

Implements DeviceOps with the v2 OP_TEST oracle semantics (response payload =
first C2H bytes of request payload) and optional fault injection for negative
state-machine tests: dropped completion, stale seq, corrupt frames, delay.
"""
import time
from dataclasses import dataclass

from pcie_contract import contract as c
from pcie_transport.transport import TransportError


@dataclass
class Faults:
    drop_completion: bool = False      # wait_ready always returns False
    stale_response: bool = False       # read_exact returns a frame from seq-1
    corrupt_frame: bool = False        # flip one byte of the response frame
    short_read: bool = False           # truncate the pending response
    short_write: bool = False          # write reports fewer bytes than the frame
    write_delay_s: float = 0.0         # write blocks this long (reentrancy tests)
    delay_s: float = 0.0               # wait_ready blocks this long


class MockDevice:
    def __init__(self, faults: Faults | None = None):
        self.faults = faults or Faults()
        self.pending_response: bytes | None = None
        self.pending_seq: int | None = None
        self.last_frame: bytes | None = None
        self.ready_seq: int | None = None
        self.flushes = 0
        self.notifies = 0

    def write(self, frame: bytes, *, deadline: float) -> int:
        if self.faults.write_delay_s:
            time.sleep(self.faults.write_delay_s)
        self.last_frame = frame
        header, _ = c.unpack_request(frame)
        payload = frame[c.HEADER_BYTES:]
        if header.op == c.OP_RESET_CACHE:
            response_payload = b""
        elif header.op == c.OP_TEST:
            response_payload = c.test_response_payload(payload)
        else:
            response_payload = bytes(c.C2H_PAYLOAD_BYTES)
        response = c.pack_response(header.seq, header.layer, header.position,
                                   response_payload, op=header.op)
        if self.faults.stale_response and header.seq > 1:
            stale_payload = c.test_response_payload(payload) if header.op == c.OP_TEST else b""
            response = c.pack_response(header.seq - 1, header.layer, header.position,
                                       stale_payload, op=header.op)
        if self.faults.corrupt_frame:
            response = bytes([response[0] ^ 0xFF]) + response[1:]
        if self.faults.short_read:
            response = response[:10]
        self.pending_response = response
        self.pending_seq = header.seq
        if self.faults.drop_completion:
            self.ready_seq = None
        else:
            self.ready_seq = header.seq
        return len(frame) // 2 if self.faults.short_write else len(frame)

    def wait_ready(self, seq: int, *, deadline: float) -> bool:
        if self.faults.delay_s:
            end = time.monotonic() + self.faults.delay_s
            while time.monotonic() < end and time.monotonic() < deadline:
                time.sleep(0.001)
        if self.faults.delay_s and time.monotonic() >= deadline:
            return False
        return self.ready_seq == seq

    def read_exact(self, count: int, *, deadline: float) -> bytes:
        if self.pending_response is None:
            raise TransportError("No pending response")
        if len(self.pending_response) < count:
            raise TransportError(f"Short read: want {count}, have {len(self.pending_response)}")
        data = self.pending_response[:count]
        self.pending_response = None
        return data

    def notify(self) -> None:
        self.notifies += 1

    def flush_queues(self) -> None:
        self.flushes += 1
        self.pending_response = None
        self.pending_seq = None
        self.ready_seq = None


def make_device(binding):
    """Board-runner hook for PC self-tests only (never board evidence)."""
    del binding
    return MockDevice()
