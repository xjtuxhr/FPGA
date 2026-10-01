"""Binding evidence record and UNBOUND guard.

Fields mirror the handover table in pcie_contract/TRANSPORT_BINDING.md.
transport.py refuses to touch any device while the binding is incomplete.
A bound record must carry evidence (board log, node listing, BAR resource
readout) and is versioned; it never guesses device nodes or offsets.
"""
from dataclasses import dataclass, asdict, field
import json
from pathlib import Path


class BindingError(RuntimeError):
    """Binding is missing, incomplete, or inconsistent."""


@dataclass(frozen=True)
class Binding:
    binding_version: int
    contract_version: int
    evidence_ref: str = ""          # path/commit of the raw board evidence
    bdf: str = ""
    vendor_device: str = ""         # e.g. "1edb:abcd"
    bound_driver: str = ""
    bars: str = ""                  # recorded BAR resource table (text)
    h2c_node: str = ""
    c2h_node: str = ""
    control_node: str = ""
    node_permissions: str = ""
    access_method: str = ""         # how control access is performed (validated only)
    address_formula: str = ""       # API / BAR index / driver base / logical offset
    data_mode: str = ""             # AXI-MM or AXI-ST
    aximm_buffers: str = ""
    axist_framing: str = ""
    dma_alignment: str = ""
    dma_length_granularity: str = ""
    dma_max_length: str = ""
    dma_padding: str = ""
    coherence_sync: str = ""
    submit_order: str = ""          # prepare C2H first, or H2C first
    write_return_meaning: str = ""
    input_visibility: str = ""
    request_accepted: str = ""
    dma_completion: str = ""
    attention_completion: str = ""
    stale_done_clear: str = ""
    readback_consume: str = ""
    timeout_handling: str = ""
    short_io_handling: str = ""
    error_recovery: str = ""
    clock_method: str = ""
    poll_interval: str = ""
    correctness_method: str = ""

    @property
    def is_bound(self) -> bool:
        required = {
            "binding_version", "contract_version", "bdf", "vendor_device",
            "h2c_node", "c2h_node", "control_node", "access_method",
            "data_mode", "dma_alignment", "dma_length_granularity",
            "submit_order", "dma_completion", "attention_completion",
            "timeout_handling", "clock_method",
        }
        return all(getattr(self, name) for name in required)

    @classmethod
    def load(cls, path: Path) -> "Binding":
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_file():
            raise BindingError(f"Binding file missing: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            binding = cls(**data)
        except TypeError as exc:
            raise BindingError(f"Binding file has unknown fields: {exc}") from exc
        if not binding.is_bound:
            missing = [name for name in data if not getattr(binding, name)]
            raise BindingError(f"Binding incomplete; missing evidence for: {missing}")
        if binding.contract_version != 2:
            raise BindingError(f"Binding targets contract v{binding.contract_version}, codec is v2")
        if binding.vendor_device != "1edb:abcd":
            raise BindingError(f"Binding must target 1edb:abcd, got {binding.vendor_device}")
        return binding

    def save(self, path: Path) -> None:
        if not self.is_bound:
            raise BindingError("Refusing to save an incomplete binding")
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
