"""Application status word decode (PCIE003_INTERFACE_SPEC.md section 4).

Pure, standard-library only, NO device access. Layout (32-bit):

    [0]     DONE   layer logic finished, C2H output ready
    [3:1]   ERR    0=OK, 1=SEQ_ERR, 2=LAYER_ERR, 3=CRC_ERR
    [31:4]  reserved (perf/layer/position later)

The endpoint does NOT wire this word yet (B: pcie_status not instantiated) and
its control-register offset is not defined. This module only decodes a value;
reading it is done by tools/probe_status.py with an explicit, operator-supplied
offset (never a guessed address).
"""
from dataclasses import dataclass

ERR_OK = 0
ERR_SEQ = 1
ERR_LAYER = 2
ERR_CRC = 3
ERR_NAMES = {ERR_OK: "OK", ERR_SEQ: "SEQ_ERR", ERR_LAYER: "LAYER_ERR", ERR_CRC: "CRC_ERR"}


@dataclass(frozen=True)
class StatusWord:
    raw: int

    @property
    def done(self) -> bool:
        return bool(self.raw & 0x1)

    @property
    def err(self) -> int:
        return (self.raw >> 1) & 0x7

    @property
    def err_name(self) -> str:
        return ERR_NAMES.get(self.err, "RESERVED")

    @property
    def reserved(self) -> int:
        return (self.raw >> 4) & 0x0FFFFFFF

    @property
    def ok(self) -> bool:
        return self.err == ERR_OK

    def describe(self) -> str:
        return "DONE=%d ERR=%d(%s) reserved=0x%07x" % (
            int(self.done), self.err, self.err_name, self.reserved)


def decode(value: int) -> StatusWord:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"status word must be a uint32, got {value!r}")
    return StatusWord(value)
