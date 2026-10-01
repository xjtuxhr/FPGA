"""Binding evidence record and UNBOUND guard.

Fields mirror the handover table in pcie_contract/TRANSPORT_BINDING.md.
transport.py refuses to touch any device while the binding is incomplete.
Validation is centralized: construction, load(), save() and the Transport
entry all enforce the same rules (contract version, target device, kind,
binding version). A bound record must carry evidence (board log, node
listing, BAR resource readout) and is versioned; it never guesses device
nodes or offsets.
"""
from dataclasses import dataclass, asdict
import json
from pathlib import Path

KIND_REAL = "real"
KIND_MOCK = "mock"


class BindingError(RuntimeError):
    """Binding is missing, incomplete, or inconsistent."""


@dataclass(frozen=True)
class Binding:
    kind: str                       # "real" board binding or "mock" test binding
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

    _REQUIRED_EVIDENCE_CORE = {
        "binding_version", "contract_version", "bdf", "vendor_device",
        "h2c_node", "c2h_node", "control_node", "access_method",
        "data_mode", "dma_alignment", "dma_length_granularity",
        "submit_order", "dma_completion", "attention_completion",
        "timeout_handling", "clock_method",
    }
    _REQUIRED_EVIDENCE_REAL = _REQUIRED_EVIDENCE_CORE | {
        "evidence_ref", "bound_driver", "bars", "address_formula",
    }

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Centralized rule set shared by construction, load, save and Transport."""
        if self.kind not in (KIND_REAL, KIND_MOCK):
            raise BindingError(f"kind must be {KIND_REAL!r} or {KIND_MOCK!r}, got {self.kind!r}")
        if type(self.binding_version) is not int or self.binding_version <= 0:
            raise BindingError("binding_version must be a positive integer")
        if self.contract_version != 2:
            raise BindingError(f"Binding targets contract v{self.contract_version}, codec is v2")
        if self.vendor_device != "1edb:abcd":
            raise BindingError(f"Binding must target 1edb:abcd, got {self.vendor_device!r}")
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if field_name == "kind" or field_name in self._REQUIRED_EVIDENCE_REAL:
                continue
            if not isinstance(value, str):
                raise BindingError(f"{field_name} must be a string, got {type(value).__name__}")

    @property
    def is_bound(self) -> bool:
        """Evidence completeness, kind-aware.

        A real board binding additionally requires the handover evidence
        named in TRANSPORT_BINDING.md (evidence_ref, bound_driver, bars,
        address_formula); a mock binding only needs the core access fields.
        """
        required = (self._REQUIRED_EVIDENCE_REAL if self.kind == KIND_REAL
                    else self._REQUIRED_EVIDENCE_CORE)
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
        return binding

    def save(self, path: Path) -> None:
        self.validate()
        if not self.is_bound:
            raise BindingError("Refusing to save an incomplete binding")
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
