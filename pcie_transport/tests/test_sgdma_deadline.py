"""PC-only tests for the interruptible H2C-write deadline mechanism.

Uses an anonymous pipe as a stand-in for a blocking char device and verifies
the SIGALRM-based mechanism aborts a blocking syscall at the deadline. It opens
no device, touches no BAR and is NOT board evidence.
"""
import os
import threading
import time
import signal
import unittest

from pcie_transport.sgdma_device import _Deadline, _interruptible_deadline
from pcie_transport.transport import TransportError

POSIX_TIMER = hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


class InterruptibleDeadlineTests(unittest.TestCase):
    @unittest.skipUnless(POSIX_TIMER, "SIGALRM/setitimer are POSIX-only")
    def test_blocking_read_aborted_at_deadline(self):
        read_fd, write_fd = os.pipe()
        try:
            deadline = time.monotonic() + 0.3
            start = time.monotonic()
            with self.assertRaises(_Deadline):
                with _interruptible_deadline(deadline):
                    os.read(read_fd, 1)  # blocks: no data, writer still open
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, 0.25)
            self.assertLess(elapsed, 1.5)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_expired_deadline_raises_before_blocking(self):
        with self.assertRaises(TransportError):
            with _interruptible_deadline(time.monotonic() - 1.0):
                pass

    def test_non_main_thread_is_not_armed(self):
        result = {}

        def worker():
            with _interruptible_deadline(time.monotonic() + 1.0) as armed:
                result["armed"] = armed

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertFalse(result["armed"])


if __name__ == "__main__":
    unittest.main()
