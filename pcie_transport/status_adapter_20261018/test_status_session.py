import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from pcie_contract import contract as codec
from pcie_transport.binding import Binding
from pcie_transport.transport import Transport, TransportError

from status_adapter import (
    AbortableDevice,
    MockStatus,
    STATUS_DONE,
    STATUS_FAULT,
    STATUS_READY,
    StatusTransport,
)
from status_session import StatusConfig, StatusSession, run_op_test


class MockWire:
    """Minimal in-process DeviceOps for RESET/TEST protocol tests."""

    deadline_enforced = False

    def __init__(self, status):
        self.status = status
        self.writes = []
        self.response = b""
        self.closed = False

    def write(self, frame, *, deadline):
        self.status.status = STATUS_READY
        header, payload = codec.unpack_request(frame)
        self.writes.append((header.op, header.seq))
        if header.op == codec.OP_RESET_CACHE:
            self.response = codec.pack_response(
                header.seq, header.layer, header.position, b"",
                op=codec.OP_RESET_CACHE,
            )
        elif header.op == codec.OP_TEST:
            self.response = codec.pack_response(
                header.seq, header.layer, header.position,
                payload[:codec.C2H_PAYLOAD_BYTES], op=codec.OP_TEST,
            )
        else:
            raise AssertionError("unexpected op in mock")
        self.status.status |= STATUS_DONE
        return len(frame)

    def wait_ready(self, seq, *, deadline):
        return True

    def read_exact(self, count, *, deadline):
        if len(self.response) < count:
            raise AssertionError("mock response too short")
        return self.response[:count]

    def notify(self):
        pass

    def flush_queues(self):
        pass

    def close(self):
        self.closed = True


class StatusSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = Binding.load(REPO_ROOT / "pcie_transport/bindings/board_20261011.json")

    def make_session(self, status=None, *, abort_fn=None):
        status = status or MockStatus(STATUS_READY)
        wire = MockWire(status)
        device = AbortableDevice(
            StatusTransport(wire, status),
            abort_fn=abort_fn or (lambda: None),
        )
        transport = Transport(device, self.binding)
        config = StatusConfig(
            bar_id=0,
            status_offset=0xA4,
            control_offset=0xA8,
            node="/dev/null",
            abort_node="/dev/null",
        )
        return StatusSession(transport, device, status, config), wire

    def test_reset_and_two_test_rounds(self):
        session, wire = self.make_session()
        results = run_op_test(session, start_seq=7000, rounds=2)
        self.assertEqual([r["op"] for r in results], ["RESET_CACHE", "TEST", "TEST"])
        self.assertEqual([w[0] for w in wire.writes],
                         [codec.OP_RESET_CACHE, codec.OP_TEST, codec.OP_TEST])
        self.assertIs(session.deadline_enforced, False)

    def test_not_ready_blocks_before_write(self):
        session, wire = self.make_session(status=MockStatus(0))
        with self.assertRaises(TransportError):
            run_op_test(session, start_seq=7000, rounds=1)
        self.assertEqual(wire.writes, [])

    def test_fault_after_write_fails_stop(self):
        status = MockStatus(STATUS_READY)

        class FaultWire(MockWire):
            def write(self, frame, *, deadline):
                result = super().write(frame, deadline=deadline)
                self.status.status = STATUS_READY | STATUS_FAULT
                return result

        wire = FaultWire(status)
        device = AbortableDevice(StatusTransport(wire, status), abort_fn=lambda: None)
        transport = Transport(device, self.binding)
        session = StatusSession(transport, device, status, StatusConfig(
            bar_id=0, status_offset=0xA4, control_offset=0xA8))
        with self.assertRaises(TransportError):
            run_op_test(session, start_seq=7000, rounds=1)
        self.assertEqual(len(wire.writes), 1)

    def test_config_requires_frozen_offsets(self):
        with self.assertRaises(ValueError):
            StatusConfig(bar_id=0, status_offset=None, control_offset=0xA8).validate()
        with self.assertRaises(ValueError):
            StatusConfig(bar_id=0, status_offset=0xA4, control_offset=None).validate()

    def test_config_accepts_candidate(self):
        StatusConfig(bar_id=0, status_offset=0xA4, control_offset=0xA8).validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
