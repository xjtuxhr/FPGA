"""Real SGDMA device adapter (PC2). NOT BOUND until PCIe enumeration.

Filled in AFTER the PCIe endpoint enumerates: this maps the transport DeviceOps
to the vendor SGDMA character devices (H2C/C2H/control) described by the binding
(see pcie_contract/TRANSPORT_BINDING.md). Until the real nodes/offsets are
measured, every hardware call fails closed -- do NOT guess BAR offsets,
registers or ioctl shapes.

Implemented later (per binding):
  write()       -> H2C character device write (full frame, with notify)
  read_exact()  -> C2H character device read
  notify()      -> doorbell / completion notification (per binding)
  wait_ready()  -> poll status word [0]=DONE (see PCIE003_INTERFACE_SPEC.md)
  flush_queues()-> drain/isolate queues on recovery
"""
from pcie_transport.binding import Binding, BindingError


class SgdmaDevice:
    def __init__(self, binding: Binding):
        if not isinstance(binding, Binding) or not binding.is_bound:
            raise BindingError("SgdmaDevice requires a complete binding")
        binding.validate()
        if binding.kind != "real":
            raise BindingError("SgdmaDevice is for kind=real bindings only")
        self.binding = binding

    def _todo(self, what: str) -> None:
        raise NotImplementedError(
            f"{what} not implemented yet: fill from PCIe enumeration evidence "
            f"(h2c={self.binding.h2c_node!r} c2h={self.binding.c2h_node!r} "
            f"ctrl={self.binding.control_node!r})"
        )

    def write(self, frame: bytes, *, deadline: float) -> int:
        self._todo("SGDMA H2C write")

    def read_exact(self, count: int, *, deadline: float) -> bytes:
        self._todo("SGDMA C2H read")

    def notify(self) -> None:
        self._todo("doorbell/completion notification")

    def wait_ready(self, seq: int, *, deadline: float) -> bool:
        self._todo("DONE/status poll")

    def flush_queues(self) -> None:
        self._todo("queue flush on recovery")


def make_device(binding: Binding) -> SgdmaDevice:
    return SgdmaDevice(binding)
