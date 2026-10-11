"""Real SGDMA device adapter (PC2).

Maps the transport ``DeviceOps`` to the vendor SGDMA character devices
(``/dev/ANLOGIC-PCI0_{h2c_0,c2h_0,control}``) named by a ``kind=real`` binding.
No BAR address, register offset or ioctl shape is hardcoded here; only the
nodes described by the binding are used.

Evidence-verified behavior (2026-10-11, v2 endpoint bit
``imx415_pcie_4k.bit`` sha256 8FA867D7...BEF9; see
``docs/PROJECT_STATUS_SNAPSHOT_20261011.md``):

- H2C: a single ``os.write`` of the logical frame (1952B ``OP_TEST`` /
  32B ``RESET_CACHE``) submits the SGDMA transfer; frames are not fragmented
  (short write is a hard error).
- C2H: ``os.read`` from the c2h char device returns the logical frame
  (1184B ``OP_TEST`` / 32B reset ack). Reads are non-blocking and bounded by
  one monotonic deadline via ``select``.
- ``notify``: the char-device write is the submission; there is no separate
  doorbell on this binding, so it is a documented no-op (never a fake ACK).
- ``wait_ready``: no application status word is wired yet (PCIE003 spec TODO);
  completion is proven by a complete, contract-validated C2H frame read under
  the deadline, so this returns True without polling a non-existent bit.
"""
import errno
import os
import select
import time

from pcie_transport.binding import Binding, BindingError
from pcie_transport.transport import TransportError


class SgdmaDevice:
    def __init__(self, binding: Binding):
        if not isinstance(binding, Binding) or not binding.is_bound:
            raise BindingError("SgdmaDevice requires a complete binding")
        binding.validate()
        if binding.kind != "real":
            raise BindingError("SgdmaDevice is for kind=real bindings only")
        for name, path in (("h2c", binding.h2c_node), ("c2h", binding.c2h_node)):
            if not path.startswith("/dev/"):
                raise BindingError(f"{name} node must be an absolute /dev path, got {path!r}")
            if not os.path.exists(path):
                raise BindingError(f"{name} node missing: {path}")
        self.binding = binding
        self._h2c_fd = None
        self._c2h_fd = None

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
        try:
            return os.write(self._open_h2c(), frame)
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


def make_device(binding: Binding) -> SgdmaDevice:
    return SgdmaDevice(binding)
