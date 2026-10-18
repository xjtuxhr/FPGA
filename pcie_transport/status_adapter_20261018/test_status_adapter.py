import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from status_adapter import (
    AbortableDevice,
    CONTROL_SOFT_RESET,
    DeadlineAbort,
    Fault,
    MockStatus,
    NotReady,
    RealBarStatus,
    STATUS_BUSY,
    STATUS_DONE,
    STATUS_ERR_MASK,
    STATUS_ERR_SHIFT,
    STATUS_FAULT,
    STATUS_READY,
    StatusError,
    StatusTransport,
)


class MockInner:
    deadline_enforced = False

    def __init__(self, status):
        self.status = status
        self.writes = []
        self.reads = []
        self.notified = 0
        self.flushed = 0
        self.closed = False

    def write(self, frame, *, deadline):
        self.writes.append(frame)
        self.status.status |= STATUS_DONE
        return len(frame)

    def read_exact(self, count, *, deadline):
        self.reads.append(count)
        return bytes(count)

    def notify(self):
        self.notified += 1

    def flush_queues(self):
        self.flushed += 1

    def close(self):
        self.closed = True


class BlockingInner:
    deadline_enforced = False

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.aborted = False
        self.abort_calls = 0

    def write(self, frame, *, deadline):
        self.started.set()
        self.release.wait(2.0)
        if self.aborted:
            raise OSError(125, "Operation canceled")
        return len(frame)

    def read_exact(self, count, *, deadline):
        return bytes(count)

    def notify(self):
        pass

    def flush_queues(self):
        pass

    def close(self):
        pass


class StatusAdapterTests(unittest.TestCase):
    def test_not_ready_blocks_write(self):
        status = MockStatus(0)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        with self.assertRaises(NotReady):
            transport.write(b"frame", deadline=time.monotonic() + 0.05)
        self.assertEqual(inner.writes, [])

    def test_ready_then_done(self):
        status = MockStatus(STATUS_READY)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        self.assertEqual(transport.write(b"frame", deadline=time.monotonic() + 0.5), 5)
        self.assertTrue(transport.wait_ready(1, deadline=time.monotonic() + 0.5))
        self.assertEqual(inner.writes, [b"frame"])

    def test_fault_blocks_write(self):
        status = MockStatus(STATUS_READY | STATUS_FAULT)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        with self.assertRaises(Fault):
            transport.write(b"frame", deadline=time.monotonic() + 0.5)
        self.assertEqual(inner.writes, [])

    def test_err_blocks_done(self):
        status = MockStatus(STATUS_READY)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        status.status = STATUS_DONE | (3 << STATUS_ERR_SHIFT)
        with self.assertRaises(Fault):
            transport.wait_ready(1, deadline=time.monotonic() + 0.5)

    def test_done_timeout(self):
        status = MockStatus(STATUS_READY)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        status.status = STATUS_READY | STATUS_BUSY
        with self.assertRaises(StatusError):
            transport.wait_ready(1, deadline=time.monotonic() + 0.05)

    def test_soft_reset_clears_fault(self):
        status = MockStatus(STATUS_FAULT)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        self.assertTrue(transport.soft_reset(deadline=time.monotonic() + 0.5))
        self.assertEqual(status.controls, [CONTROL_SOFT_RESET])
        self.assertEqual(status.status & STATUS_READY, STATUS_READY)
        self.assertEqual(status.status & STATUS_FAULT, 0)

    def test_deadline_flag_stays_false(self):
        status = MockStatus(STATUS_READY)
        transport = StatusTransport(MockInner(status), status)
        self.assertIs(transport.deadline_enforced, False)

    def test_two_sessions_after_reset(self):
        status = MockStatus(STATUS_READY)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        self.assertTrue(transport.write(b"one", deadline=time.monotonic() + 0.5))
        self.assertTrue(transport.wait_ready(1, deadline=time.monotonic() + 0.5))
        status.status = STATUS_FAULT
        self.assertTrue(transport.soft_reset(deadline=time.monotonic() + 0.5))
        self.assertTrue(transport.write(b"two", deadline=time.monotonic() + 0.5))
        self.assertTrue(transport.wait_ready(2, deadline=time.monotonic() + 0.5))
        self.assertEqual(inner.writes, [b"one", b"two"])

    def test_real_backend_refuses_missing_offsets(self):
        with self.assertRaises(ValueError):
            RealBarStatus(bar_id=0, status_offset=None, control_offset=0x100)
        with self.assertRaises(ValueError):
            RealBarStatus(bar_id=1, status_offset=0x100, control_offset=None)

    def test_close_closes_inner_and_status(self):
        status = MockStatus(STATUS_READY)
        inner = MockInner(status)
        transport = StatusTransport(inner, status)
        transport.close()
        self.assertTrue(inner.closed)


class AbortableTests(unittest.TestCase):
    def test_normal_write_does_not_abort(self):
        inner = MockInner(MockStatus(STATUS_READY))
        calls = []
        dev = AbortableDevice(inner, abort_fn=lambda: calls.append(1))
        self.assertEqual(dev.write(b"ok", deadline=time.monotonic() + 1.0), 2)
        self.assertEqual(calls, [])

    def test_blocked_write_aborts_at_deadline(self):
        inner = BlockingInner()

        def abort():
            inner.abort_calls += 1
            inner.aborted = True
            inner.release.set()

        dev = AbortableDevice(inner, abort_fn=abort, abort_grace_s=1.0)
        t0 = time.monotonic()
        with self.assertRaises(DeadlineAbort):
            dev.write(b"blocked", deadline=t0 + 0.15)
        elapsed = time.monotonic() - t0
        self.assertEqual(inner.abort_calls, 1)
        self.assertGreaterEqual(elapsed, 0.10)
        self.assertLess(elapsed, 1.0)

    def test_deadline_flag_stays_false(self):
        inner = MockInner(MockStatus(STATUS_READY))
        dev = AbortableDevice(inner, abort_fn=lambda: None)
        self.assertIs(dev.deadline_enforced, False)
        self.assertTrue(dev.abort_supported)

    def test_abort_fn_failure_is_reported(self):
        inner = BlockingInner()
        threading.Timer(0.3, inner.release.set).start()
        dev = AbortableDevice(inner, abort_fn=lambda: (_ for _ in ()).throw(OSError("no ioctl")),
                              abort_grace_s=1.0)
        with self.assertRaises(DeadlineAbort):
            dev.write(b"blocked", deadline=time.monotonic() + 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
