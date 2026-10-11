"""PC2 host-facing transport plugin (``module:factory``) for PC1's scheduler.

Loaded by PC1 via ``plugin_transport("pcie_transport.host_plugin:make_transport",
config=<model config>, options=<dict>)`` (see PC1 host/backends/framed_attention.py).
It wraps the real SGDMA device and answers the v2 framed request/response.

Contract with PC1's host:
- ``exchange(request, *, timeout_s) -> response_frame``: one request in flight;
  the transport enforces a single finite deadline over write + wait + read and
  returns the raw C2H frame (the host owns seq/layer/position/CRC verification).
- ``close()``.
- ``metadata()``: declaration used by ``plugin_transport``. Every flag reports
  only VERIFIED capability; ``attention_supported`` stays False until the
  endpoint actually implements ``ATTENTION(op=0)`` (it does not yet).

This plugin does NOT hardcode any BAR address; it uses the nodes from the
kind=real binding passed in ``options['binding']``.
"""
import time
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport.binding import Binding
from pcie_transport.sgdma_device import SgdmaDevice
from pcie_transport.transport import TransportError


class BoardTransport:
    def __init__(self, device, binding, *, default_timeout_s=5.0, attention_supported=False):
        self.device = device
        self.binding = binding
        self.default_timeout_s = float(default_timeout_s)
        self._attention_supported = bool(attention_supported)
        self._closed = False

    def metadata(self):
        return {
            "protocol_version": 2,
            "wire_dtype": "fp16_le",
            "max_inflight": 1,
            "hardware_transport": True,
            "binding_verified": bool(self.binding.is_bound),
            # Capability flags report VERIFIED capability only:
            # - attention/KV-write/policy control plane are NOT implemented yet,
            # - deadline_enforced depends on the interruptible H2C write mechanism.
            "attention_supported": self._attention_supported,
            "policy_configured": False,
            "deadline_enforced": bool(getattr(self.device, "deadline_enforced", False)),
            "supported_ops": ["reset_cache", "test"],
            "kv_write_supported": False,
        }

    def exchange(self, request: bytes, *, timeout_s: float) -> bytes:
        if self._closed:
            raise TransportError("transport closed")
        if not isinstance(request, bytes) or not request:
            raise TransportError("request must be non-empty bytes")
        budget = self.default_timeout_s if timeout_s is None else float(timeout_s)
        if not budget > 0:
            raise TransportError("timeout_s must be finite and positive")
        deadline = time.monotonic() + budget
        # Validate the H2C frame and derive the expected C2H frame size.
        header, _ = c.unpack_request(request)
        response_size = (c.HEADER_BYTES if header.op == c.OP_RESET_CACHE
                         else c.HEADER_BYTES + c.C2H_PAYLOAD_BYTES)
        written = self.device.write(request, deadline=deadline)
        if written != len(request):
            raise TransportError(f"short H2C write {written}/{len(request)}; no fragmentation retry")
        self.device.notify()
        if not self.device.wait_ready(header.seq, deadline=deadline):
            raise TransportError("wait_ready deadline expired")
        return self.device.read_exact(response_size, deadline=deadline)

    def close(self):
        self._closed = True
        close = getattr(self.device, "close", None)
        if callable(close):
            close()


def make_transport(config=None, options=None):
    """PC2 factory: ``pcie_transport.host_plugin:make_transport``.

    ``options`` must contain ``binding`` = path to a kind=real binding JSON.
    Optional: ``timeout_s`` (default 5.0), ``attention_supported`` (default
    False -- flip only after ATTENTION is verified on hardware).
    """
    options = dict(options or {})
    binding_path = options.get("binding")
    if not binding_path:
        raise ValueError("options['binding'] (path to kind=real binding JSON) is required")
    binding = Binding.load(Path(binding_path))
    if binding.kind != "real":
        raise ValueError("host plugin requires a kind=real binding")
    device = SgdmaDevice(binding)
    return BoardTransport(device, binding,
                          default_timeout_s=options.get("timeout_s", 5.0),
                          attention_supported=bool(options.get("attention_supported", False)))
