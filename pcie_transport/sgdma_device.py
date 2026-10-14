"""Real SGDMA device adapter (PC2).

Maps the transport ``DeviceOps`` to the vendor SGDMA character devices
(``/dev/ANLOGIC-PCI0_{h2c_0,c2h_0,control}``) named by a ``kind=real`` binding.
No BAR address, register offset or ioctl shape is hardcoded here; only the
nodes described by the binding are used.

Deadlines (evidence-backed, see ``pcie_transport/H2C_WRITE_TIMEOUT.md``):

- The vendor driver submits each frame as a descriptor and waits with
  ``al_wait_event_interruptible_timeout`` bounded by the ``h2c_timeout`` /
  ``c2h_timeout`` module parameters (default 10 s; confirmed live via
  ``/sys/module/anlogic_pci/parameters/h2c_timeout``). The wait is
  *interruptible*: a signal aborts it early, and the driver then aborts the
  transfer, stops the engine and returns ``-ERESTARTSYS``.
- C2H reads are bounded by ``select`` on a non-blocking fd.
- H2C ``os.write`` is intended to be bounded by the same interruptible wait:
  a per-request ``SIGALRM`` (main thread only) raises at the deadline. NOTE:
  a timed-out H2C write leaves the SGDMA engine stopped, so the endpoint MUST
  be reset before reuse (abort-and-recover, not a clean cancel).
  BOARD RESULT 2026-10-14: the SIGALRM did NOT abort the write early -- it
  returned at the driver ``h2c_timeout`` (10 s), not our deadline. So
  ``deadline_enforced`` is False unless explicitly verified; see
  ``H2C_WRITE_TIMEOUT.md`` and ``BOARD_VERIFICATION_CHECKLIST_H2C_DEADLINE.md``.
- ``notify`` is a documented no-op (the char-device write is the submission);
  ``wait_ready`` returns without inventing a status bit (no application status
  register is wired yet -- see PCIE003_INTERFACE_SPEC.md TODO).
"""
import contextlib
import errno
import os
import select
import signal
import threading
import time

from pcie_transport.binding import Binding, BindingError
from pcie_transport.transport import TransportError


class _Deadline(Exception):
    """Internal: raised from the SIGALRM handler to abort an interruptible wait."""


@contextlib.contextmanager
def _interruptible_deadline(deadline: float):
    """Arm a SIGALRM that aborts a blocking syscall at ``deadline``.

    Valid only in the main thread. Yields True if armed, False if the
    mechanism is unavailable (then the driver's own ``h2c_timeout`` bound is
    the only ceiling and the caller must detect late returns).
    """
    if deadline - time.monotonic() <= 0:
        raise TransportError("deadline already expired before blocking call")
    if (threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer")):
        yield False
        return
    remaining = deadline - time.monotonic()

    def _handler(signum, frame):
        raise _Deadline()

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class SgdmaDevice:
    def __init__(self, binding: Binding, *, deadline_verified: bool = False):
        if not isinstance(binding, Binding) or not binding.is_bound:
            raise BindingError("SgdmaDevice requires a complete binding")
        binding.validate()
        if binding.kind != "real":
            raise BindingError("SgdmaDevice is for kind=real bindings only")
        self._deadline_verified = bool(deadline_verified)
        for name, path in (("h2c", binding.h2c_node), ("c2h", binding.c2h_node)):
            if not path.startswith("/dev/"):
                raise BindingError(f"{name} node must be an absolute /dev path, got {path!r}")
            if not os.path.exists(path):
                raise BindingError(f"{name} node missing: {path}")
        self.binding = binding
        self._h2c_fd = None
        self._c2h_fd = None

    @property
    def deadline_enforced(self) -> bool:
        """True only when the interruptible-deadline mechanism is BOTH available
        AND verified to work on this board.

        2026-10-14 board result (BOARD_VERIFICATION_CHECKLIST_H2C_DEADLINE.md):
        a blocking H2C write was NOT aborted at our 0.5 s deadline -- it returned
        at the driver ``h2c_timeout`` (10 s). So the SIGALRM ceiling did NOT take
        effect and this stays False. An operator may pass ``deadline_verified=True``
        only after a GREEN board run; do not infer it from thread/POSIX alone.
        """
        return (self._deadline_verified
                and threading.current_thread() is threading.main_thread()
                and hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer"))

    def _open_h2c(self) -> int:
        if self._h2c_fd is None:
            self._h2c_fd = os.open(self.binding.h2c_node, os.O_WRONLY)
        return self._h2c_fd

    def _open_c2h(self) -> int:
        if self._c2h_fd is None:
            self._c2h_fd = os.open(self.binding.c2h_node, os.O_RDONLY | os.O_NONBLOCK)
        return self._c2h_fd

    def write(self, frame: bytes, *, deadline: float) -> int:
        if not isinstance(frame, bytes) or not frame:
            raise TransportError("H2C frame must be non-empty bytes")
        fd = self._open_h2c()
        with _interruptible_deadline(deadline):
            try:
                return os.write(fd, frame)
            except _Deadline as exc:
                raise TransportError(
                    "H2C write aborted at deadline; driver stopped the SGDMA engine, "
                    "endpoint requires reset before reuse") from exc
            except InterruptedError as exc:
                raise TransportError(f"H2C write interrupted (EINTR): {exc}") from exc
            except OSError as exc:
                raise TransportError(f"H2C write failed: {exc}") from exc

    def read_exact(self, count: int, *, deadline: float) -> bytes:
        if type(count) is not int or count <= 0:
            raise TransportError("read count must be a positive int")
        fd = self._open_c2h()
        buf = bytearray()
        while len(buf) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError(f"C2H deadline expired at {len(buf)}/{count} bytes")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise TransportError(f"C2H read timeout at {len(buf)}/{count} bytes")
            try:
                chunk = os.read(fd, count - len(buf))
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise TransportError(f"C2H read failed: {exc}") from exc
            if chunk:
                buf += chunk
        return bytes(buf)

    def notify(self) -> None:
        # The SGDMA char-device write is itself the submission; this binding has
        # no separate doorbell. Documented no-op, NOT a fabricated completion.
        return None

    def wait_ready(self, seq: int, *, deadline: float) -> bool:
        # No application status register is wired yet; the deadline is enforced
        # by read_exact(). Return True without inventing a status bit.
        return deadline - time.monotonic() > 0

    def flush_queues(self) -> None:
        fd = self._open_c2h()
        while True:
            try:
                if not os.read(fd, 65536):
                    break
            except OSError:
                break
        return None

    def close(self) -> None:
        for name in ("_h2c_fd", "_c2h_fd"):
            fd = getattr(self, name)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, name, None)


def make_device(binding: Binding, *, deadline_verified: bool = False) -> SgdmaDevice:
    return SgdmaDevice(binding, deadline_verified=deadline_verified)
