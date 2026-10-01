"""Shared PCIe wire contract: host <-> FPGA attention.

DRAFT 0.1, to be jointly reviewed (UNKNOWNS PCIE-003, freeze by D21).
Both the Python host and the FPGA RTL testbench must derive constants from
contract.json / this module. No side may hardcode protocol fields locally.
Any magic/version/seq/crc mismatch must raise immediately (fail closed).

Wire format note: this contract covers ONLY the per-layer Q/K/V upload and
attention output return. KV quantization (B/U/M) happens inside the FPGA and
is intentionally NOT part of the wire format.
"""
from dataclasses import dataclass
import json
import struct
import zlib
from pathlib import Path

_CONTRACT = json.loads(
    (Path(__file__).with_name("contract.json")).read_text(encoding="utf-8")
)

MAGIC = int(_CONTRACT["magic_hex"], 16)
PROTOCOL_VERSION = _CONTRACT["protocol_version"]
WIRE_DTYPE = _CONTRACT["wire_dtype"]
HEADER_BYTES = _CONTRACT["header_bytes"]
HEADER_LAYOUT = _CONTRACT["header_layout"]
HEADER_FMT = "<IHBBB" + "xxx" + "II" + "H" + "xx" + "II"  # 32 bytes, LE, matches contract.json

MODEL = _CONTRACT["model"]
HIDDEN = MODEL["hidden"]
KV_DIM = MODEL["kv_dim"]
LAYERS = MODEL["layers"]
VOCAB = MODEL["vocab"]
CONTEXT = MODEL["context"]

H2C_PAYLOAD_BYTES = _CONTRACT["payloads"]["h2c_bytes"]
C2H_PAYLOAD_BYTES = _CONTRACT["payloads"]["c2h_bytes"]

OP_ATTENTION = _CONTRACT["ops"]["attention"]
OP_RESET_CACHE = _CONTRACT["ops"]["reset_cache"]

STATUS_DONE = _CONTRACT["status_bits"]["done"]
STATUS_ERROR = _CONTRACT["status_bits"]["error"]
STATUS_IDLE = _CONTRACT["status_bits"]["idle"]
STATUS_VERSION_MISMATCH = _CONTRACT["status_bits"]["version_mismatch"]

CTRL_RUN = _CONTRACT["ctrl_bits"]["run"]
CTRL_RESET_CACHE = _CONTRACT["ctrl_bits"]["reset_cache"]

REG_VERSION = int(_CONTRACT["registers"]["version"], 16)
REG_CTRL = int(_CONTRACT["registers"]["ctrl"], 16)
REG_STATUS = int(_CONTRACT["registers"]["status"], 16)
REG_DOORBELL = int(_CONTRACT["registers"]["doorbell"], 16)
REG_ATTN_MS = int(_CONTRACT["registers"]["attn_ms"], 16)

_FLAG_RESET = 1 << 0
_FLAG_LAST_LAYER = 1 << 1


class ContractError(RuntimeError):
    """Any protocol mismatch on the wire or in arguments."""


@dataclass(frozen=True)
class Header:
    magic: int
    version: int
    op: int
    flags: int
    layer: int
    position: int
    seq: int
    payload_len: int
    crc32c: int

    def check(self, *, op: int | None = None) -> None:
        if self.magic != MAGIC:
            raise ContractError(f"Bad magic 0x{self.magic:08X}")
        if self.version != PROTOCOL_VERSION:
            raise ContractError(f"Version mismatch: got {self.version}, expect {PROTOCOL_VERSION}")
        if op is not None and self.op != op:
            raise ContractError(f"Unexpected op {self.op}, expect {op}")
        if self.payload_len > max(H2C_PAYLOAD_BYTES, C2H_PAYLOAD_BYTES):
            raise ContractError(f"payload_len {self.payload_len} out of range")
        if not 0 <= self.layer < LAYERS:
            raise ContractError(f"layer {self.layer} out of range")
        if not 0 <= self.position < CONTEXT:
            raise ContractError(f"position {self.position} out of range")


def crc32c(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pack_header(header: Header) -> bytes:
    return struct.pack(
        HEADER_FMT,
        header.magic,
        header.version,
        header.op,
        header.flags,
        header.layer,
        header.position,
        header.seq,
        header.payload_len,
        header.crc32c,
        0,
    )


def unpack_header(buf: bytes) -> Header:
    if len(buf) != HEADER_BYTES:
        raise ContractError(f"Header needs {HEADER_BYTES} bytes, got {len(buf)}")
    magic, version, op, flags, layer, position, seq, payload_len, crc, _reserved = struct.unpack(HEADER_FMT, buf)
    return Header(magic, version, op, flags, layer, position, seq, payload_len, crc)


def pack_request(
    seq: int,
    layer: int,
    position: int,
    payload: bytes,
    *,
    op: int = OP_ATTENTION,
    flags: int = 0,
) -> bytes:
    """Build a 1952-byte H2C frame. payload must be exactly H2C_PAYLOAD_BYTES."""
    if len(payload) != H2C_PAYLOAD_BYTES:
        raise ContractError(f"H2C payload must be {H2C_PAYLOAD_BYTES} bytes, got {len(payload)}")
    if position == 0:
        flags |= _FLAG_RESET
    header = Header(MAGIC, PROTOCOL_VERSION, op, flags, layer, position, seq,
                    H2C_PAYLOAD_BYTES, crc32c(payload))
    return pack_header(header) + payload


def unpack_response(frame: bytes, *, expect_seq: int, expect_layer: int, expect_position: int) -> tuple[Header, bytes]:
    """Unpack a C2H frame and fail closed on any mismatch."""
    if len(frame) != HEADER_BYTES + C2H_PAYLOAD_BYTES:
        raise ContractError(f"C2H frame must be {HEADER_BYTES + C2H_PAYLOAD_BYTES} bytes, got {len(frame)}")
    header = unpack_header(frame[:HEADER_BYTES])
    header.check(op=OP_ATTENTION)
    payload = frame[HEADER_BYTES:]
    if header.crc32c != crc32c(payload):
        raise ContractError("C2H CRC32C mismatch")
    if header.seq != expect_seq:
        raise ContractError(f"seq mismatch: got {header.seq}, expect {expect_seq}")
    if header.layer != expect_layer or header.position != expect_position:
        raise ContractError(
            f"layer/position mismatch: got ({header.layer},{header.position}), "
            f"expect ({expect_layer},{expect_position})"
        )
    if header.flags:
        raise ContractError(f"C2H flags must be 0, got {header.flags} (errors go via STATUS register)")
    return header, payload


def pack_f16(values) -> bytes:
    """Pack a sequence of floats to FP16 little-endian (wire format)."""
    return struct.pack(f"<{len(values)}e", *values)


def unpack_f16(payload: bytes):
    """Unpack wire payload to Python floats."""
    count = len(payload) // 2
    return struct.unpack(f"<{count}e", payload)


def _self_test() -> None:
    assert HEADER_BYTES == 32
    q = pack_f16([0.25, -0.5, 1.0, 2.5])
    assert unpack_f16(q) == (0.25, -0.5, 1.0, 2.5)
    payload = bytes(H2C_PAYLOAD_BYTES)
    frame = pack_request(7, 3, 128, payload)
    assert len(frame) == HEADER_BYTES + H2C_PAYLOAD_BYTES
    header = unpack_header(frame[:HEADER_BYTES])
    header.check(op=OP_ATTENTION)
    assert (header.seq, header.layer, header.position) == (7, 3, 128)
    assert header.crc32c == crc32c(payload)
    out_payload = bytes(C2H_PAYLOAD_BYTES)
    out_header = Header(MAGIC, PROTOCOL_VERSION, OP_ATTENTION, 0, 3, 128, 7,
                        C2H_PAYLOAD_BYTES, crc32c(out_payload))
    h2, p2 = unpack_response(pack_header(out_header) + out_payload,
                             expect_seq=7, expect_layer=3, expect_position=128)
    assert p2 == out_payload and h2 == out_header
    try:
        unpack_response(pack_header(out_header) + out_payload,
                        expect_seq=8, expect_layer=3, expect_position=128)
        raise AssertionError("seq mismatch must fail closed")
    except ContractError:
        pass
    print("contract self-test OK")


if __name__ == "__main__":
    _self_test()
