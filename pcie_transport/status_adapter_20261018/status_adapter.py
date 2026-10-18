"""Host-side READY/FAULT/DONE + SOFT_RESET adapter (B mode).

This module does NOT claim a hard H2C write deadline. READY pre-poll only
prevents writes when the endpoint already says it is not ready; it cannot
cancel a write that blocks mid-transfer.

Status/control register addresses are NOT frozen. The real backend refuses to
guess: pass explicit offsets chosen by B. The mock backend is for offline
tests and for PC1/B interface review.
"""

from __future__ import annotations

import os
import struct
import threading
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows offline use
    fcntl = None

CONTROL_NODE = "/dev/ANLOGIC-PCI0_control"
USER_NODE = "/dev/ANLOGIC-PCI0_user"

# Bits proposed in PC2_B_INTERFACE_FREEZE_DRAFT_20261018.md
STATUS_DONE = 1 << 0
STATUS_ERR_SHIFT = 1
STATUS_ERR_MASK = 0b111 << STATUS_ERR_SHIFT
STATUS_READY = 1 << 4
STATUS_FAULT = 1 << 5
STATUS_BUSY = 1 << 6

CONTROL_SOFT_RESET = 1 << 0
CONTROL_SESSION_ABORT = 1 << 1

# ANLOGIC_IOCR / ANLOGIC_IOCW from cdev_ctrl.h
_IOC_READ = 2
_IOC_WRITE = 1
_IOC_SIZE = 16
_IOC_TYPE = ord("x")
ANLOGIC_IOCR = (_IOC_READ << 30) | (_IOC_SIZE << 16) | (_IOC_TYPE << 8) | 5
ANLOGIC_IOCW = (_IOC_WRITE << 30) | (_IOC_SIZE << 16) | (_IOC_TYPE << 8) | 4
ANLOGIC_IOCABORT = (0 << 30) | (0 << 16) | (_IOC_TYPE << 8) | 11


class StatusError(RuntimeError):
    pass


class NotReady(StatusError):
    pass


class Fault(StatusError):
    pass


class DeadlineAbort(StatusError):
    """The in-flight write was aborted at the deadline; session must fail-stop."""


class BaseStatus:
    def read_status(self) -> int:
        raise NotImplementedError

    def write_control(self, value: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def poll_ready(self, deadline: float) -> bool:
        while True:
            status = self.read_status()
            if status & STATUS_FAULT:
                raise Fault("endpoint FAULT before H2C; run SOFT_RESET")
            if status & STATUS_READY:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.001)

    def poll_done(self, deadline: float) -> int:
        while True:
            status = self.read_status()
            if status & (STATUS_DONE | STATUS_FAULT | STATUS_ERR_MASK):
                return status
            if time.monotonic() >= deadline:
                raise StatusError("DONE deadline expired")
            time.sleep(0.001)

    def soft_reset(self, deadline: float) -> bool:
        self.write_control(CONTROL_SOFT_RESET)
        return self.poll_ready(deadline)


class MockStatus(BaseStatus):
    """Offline model. Tests set .status directly or via on_write callbacks."""

    def __init__(self, status: int = 0):
        self.status = status
        self.controls = []

    def read_status(self) -> int:
        return self.status

    def write_control(self, value: int) -> None:
        self.controls.append(value)
        if value & CONTROL_SOFT_RESET:
            self.status = STATUS_READY
        if value & CONTROL_SESSION_ABORT:
            self.status |= STATUS_FAULT


class RealBarStatus(BaseStatus):
    """Real BAR access. Offsets must be provided by B; no guessing.

    bar_id=0 -> BAR0 via /dev/ANLOGIC-PCI0_user or ANLOGIC ioctl bar 0.
    bar_id=1 -> BAR1 via /dev/ANLOGIC-PCI0_control or ANLOGIC ioctl bar 1.
    """

    def __init__(self, *, bar_id: int, status_offset: int | None,
                 control_offset: int | None, node: str | None = None,
                 use_ioctl: bool = False):
        if bar_id not in (0, 1):
            raise ValueError("bar_id must be 0 (user) or 1 (control)")
        if status_offset is None or control_offset is None:
            raise ValueError("status/control offsets are not frozen; refusing to guess")
        for name, value in (("status_offset", status_offset),
                            ("control_offset", control_offset)):
            if type(value) is not int or value < 0 or value & 3:
                raise ValueError(name + " must be a non-negative 4-byte aligned int")
        self.bar_id = bar_id
        self.status_offset = status_offset
        self.control_offset = control_offset
        self.node = node or (USER_NODE if bar_id == 0 else CONTROL_NODE)
        self.use_ioctl = use_ioctl
        self._fd = None

    def _open(self) -> None:
        if self._fd is None:
            self._fd = os.open(self.node, os.O_RDWR)

    def read_status(self) -> int:
        self._open()
        if self.use_ioctl:
            if fcntl is None:
                raise StatusError("fcntl unavailable; use node pread")
            req = struct.pack("<HHIII", self.bar_id, 0, self.status_offset, 0, 0)
            res = fcntl.ioctl(self._fd, ANLOGIC_IOCR, req, True)
            return struct.unpack("<HHIII", res)[4]
        return struct.unpack("<I", os.pread(self._fd, 4, self.status_offset))[0]

    def write_control(self, value: int) -> None:
        self._open()
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("control value must be uint32")
        if self.use_ioctl:
            if fcntl is None:
                raise StatusError("fcntl unavailable; use node pwrite")
            req = struct.pack("<HHIII", self.bar_id, 0, self.control_offset, value, 0)
            fcntl.ioctl(self._fd, ANLOGIC_IOCW, req)
            return
        os.pwrite(self._fd, struct.pack("<I", value), self.control_offset)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def probe_bar0(offset: int, node: str = USER_NODE) -> int:
    """Read-only path check. Does not interpret the value as status."""
    if type(offset) is not int or offset < 0 or offset & 3:
        raise ValueError("offset must be a non-negative 4-byte aligned int")
    fd = os.open(node, os.O_RDONLY)
    try:
        return struct.unpack("<I", os.pread(fd, 4, offset))[0]
    finally:
        os.close(fd)


class SgdmaAbort:
    """Abort the in-flight SGDMA transfer on a node via ANLOGIC_IOCABORT."""

    def __init__(self, node: str = "/dev/ANLOGIC-PCI0_h2c_0"):
        self.node = node

    def __call__(self) -> None:
        if fcntl is None:
            raise StatusError("fcntl unavailable; cannot abort")
        fd = os.open(self.node, os.O_RDWR)
        try:
            fcntl.ioctl(fd, ANLOGIC_IOCABORT)
        finally:
            os.close(fd)


class AbortableDevice:
    """Run an inner write in a worker; abort it via driver ioctl at deadline.

    This is a bounded *abort attempt*, not a hard deadline guarantee. On the
    tested board the abort ioctl released a blocked H2C write with
    OSError ECANCELED (125) in ~1 ms after the ioctl. The engine is stopped;
    the session must fail-stop and recovery is required.

    deadline_enforced is delegated unchanged (False). abort_supported=True only
    means the host has a best-effort abort path.
    """

    def __init__(self, inner, *, abort_fn, abort_grace_s: float = 5.0):
        if abort_grace_s <= 0:
            raise ValueError("abort_grace_s must be positive")
        self.inner = inner
        self.abort_fn = abort_fn
        self.abort_grace_s = abort_grace_s
        self.abort_supported = True

    @property
    def deadline_enforced(self) -> bool:
        return getattr(self.inner, "deadline_enforced", False)

    def write(self, frame: bytes, *, deadline: float) -> int:
        result = {}

        def worker():
            try:
                result["n"] = self.inner.write(frame, deadline=deadline)
            except BaseException as exc:  # propagated to the caller below
                result["err"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while thread.is_alive():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=min(0.01, remaining))

        if thread.is_alive():
            try:
                self.abort_fn()
            except BaseException as exc:
                thread.join(timeout=self.abort_grace_s)
                raise DeadlineAbort("abort ioctl failed: %s" % exc) from exc
            thread.join(timeout=self.abort_grace_s)
            if thread.is_alive():
                raise DeadlineAbort("abort ioctl did not release the blocked write")
            if "err" in result:
                raise DeadlineAbort("H2C write aborted at deadline") from result["err"]
            raise DeadlineAbort("H2C write aborted at deadline")

        if "err" in result:
            raise result["err"]
        return result["n"]

    def wait_ready(self, seq: int, *, deadline: float) -> bool:
        return self.inner.wait_ready(seq, deadline=deadline)

    def read_exact(self, count: int, *, deadline: float) -> bytes:
        return self.inner.read_exact(count, deadline=deadline)

    def notify(self) -> None:
        return self.inner.notify()

    def flush_queues(self) -> None:
        return self.inner.flush_queues()

    def close(self) -> None:
        return self.inner.close()


class StatusTransport:
    """DeviceOps wrapper: READY before write, DONE/ERR/FAULT after write.

    deadline_enforced is delegated unchanged (must remain False on this
    driver). This wrapper does not make a blocked write cancellable.
    """

    def __init__(self, inner, status: BaseStatus, *, poll_s: float = 1.0):
        if poll_s <= 0:
            raise ValueError("poll_s must be positive")
        self.inner = inner
        self.status = status
        self.poll_s = poll_s

    @property
    def deadline_enforced(self) -> bool:
        return getattr(self.inner, "deadline_enforced", False)

    def write(self, frame: bytes, *, deadline: float) -> int:
        if not self.status.poll_ready(deadline):
            raise NotReady("endpoint not READY before H2C; no write sent")
        return self.inner.write(frame, deadline=deadline)

    def wait_ready(self, seq: int, *, deadline: float) -> bool:
        status = self.status.poll_done(deadline)
        if status & STATUS_FAULT:
            raise Fault("endpoint FAULT while waiting for DONE")
        err = (status & STATUS_ERR_MASK) >> STATUS_ERR_SHIFT
        if err:
            raise Fault("endpoint ERR=%d while waiting for DONE" % err)
        return True

    def read_exact(self, count: int, *, deadline: float) -> bytes:
        return self.inner.read_exact(count, deadline=deadline)

    def notify(self) -> None:
        return self.inner.notify()

    def flush_queues(self) -> None:
        return self.inner.flush_queues()

    def soft_reset(self, *, deadline: float) -> bool:
        return self.status.soft_reset(deadline)

    def close(self) -> None:
        try:
            self.inner.close()
        finally:
            self.status.close()
