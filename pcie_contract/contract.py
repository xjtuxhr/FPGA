"""Protocol v2 PC codec. No device access, host implementation or BAR mapping.

contract.json is the machine-readable source. Fixed test profile is NOT a
board-verified production numeric/transport contract. See README.md.
"""
from dataclasses import dataclass, fields, replace
import json
import math
from pathlib import Path
import struct
import zlib


class ContractError(RuntimeError):
    """Malformed frame, unsupported profile or invalid software argument."""


_CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text(encoding="utf-8"))
MAGIC = int(_CONTRACT["magic_hex"], 16)
PROTOCOL_VERSION = _CONTRACT["protocol_version"]
WIRE_DTYPE = _CONTRACT["wire_dtype"]
HEADER_BYTES = _CONTRACT["header_bytes"]
HEADER_LAYOUT = _CONTRACT["header_layout"]
MODEL = _CONTRACT["model"]
HIDDEN, KV_DIM, LAYERS = MODEL["hidden"], MODEL["kv_dim"], MODEL["layers"]
VOCAB, CONTEXT = MODEL["vocab"], MODEL["context"]
GLOBAL_LAYER = _CONTRACT["global_layer"]
SEQ_MIN, SEQ_MAX = _CONTRACT["sequence_min"], _CONTRACT["sequence_max"]
H2C_PAYLOAD_BYTES = _CONTRACT["payloads"]["h2c_bytes"]
C2H_PAYLOAD_BYTES = _CONTRACT["payloads"]["c2h_bytes"]
OP_ATTENTION = _CONTRACT["ops"]["attention"]
OP_RESET_CACHE = _CONTRACT["ops"]["reset_cache"]
OP_TEST = _CONTRACT["ops"]["test"]
_OP_NAMES = {number: name for name, number in _CONTRACT["ops"].items()}


def _make_header_struct():
    """Generate packing from JSON, including explicit zero padding."""
    codes = {"u8": ("B", 1), "u16": ("H", 2), "u32": ("I", 4)}
    fmt, offset, names = "<", 0, set()
    for field in HEADER_LAYOUT:
        name, size = field["field"], field["size"]
        if name in names or field["offset"] != offset:
            raise ContractError("Duplicate, overlapping or non-contiguous header layout")
        names.add(name)
        if field["type"] == "zero_bytes":
            if type(size) is not int or size <= 0:
                raise ContractError("Invalid padding size")
            fmt += f"{size}s"
        else:
            if field["type"] not in codes or size != codes[field["type"]][1]:
                raise ContractError("Invalid integer layout")
            fmt += codes[field["type"]][0]
        offset += size
    codec = struct.Struct(fmt)
    if codec.size != HEADER_BYTES or offset != HEADER_BYTES:
        raise ContractError("Header size disagrees with JSON")
    return codec


_HEADER = _make_header_struct()
HEADER_FMT = _HEADER.format
_CRC_FIELD = next(field for field in HEADER_LAYOUT if field["field"] == "crc32")
_CRC_OFFSET, _CRC_SIZE = _CRC_FIELD["offset"], _CRC_FIELD["size"]


def crc32(data: bytes) -> int:
    """CRC-32/ISO-HDLC (IEEE), NOT Castagnoli CRC32C."""
    return zlib.crc32(data) & 0xFFFFFFFF


def _validate_schema() -> None:
    checksum = _CONTRACT["checksum"]
    expected = {
        "name": "CRC-32/ISO-HDLC", "polynomial_hex": "0x04C11DB7",
        "reflected_polynomial_hex": "0xEDB88320", "initial_hex": "0xFFFFFFFF",
        "xor_out_hex": "0xFFFFFFFF", "reflect_input": True, "reflect_output": True,
        "coverage": "32-byte header with crc32 field zeroed, followed by logical payload; DMA padding excluded",
    }
    if any(checksum.get(key) != value for key, value in expected.items()):
        raise ContractError("JSON checksum algorithm disagrees with this codec")
    if crc32(checksum["check_ascii"].encode("ascii")) != int(checksum["check_hex"], 16):
        raise ContractError("CRC known-answer check failed")
    if (int(_CONTRACT["magic_hex"], 16) != MAGIC or _CONTRACT["byte_order"] != "little"
            or struct.pack("<I", MAGIC) != _CONTRACT["magic_ascii"].encode("ascii")):
        raise ContractError("Magic byte order disagrees with JSON")
    if (_CONTRACT["wire_dtype"] != WIRE_DTYPE or WIRE_DTYPE != "fp16_le"
            or _CONTRACT["flags_allowed"] != 0 or _CONTRACT["max_inflight"] != 1):
        raise ContractError("Unsupported wire profile")
    if len(_OP_NAMES) != 3 or set(_OP_NAMES.values()) != {"attention", "reset_cache", "test"}:
        raise ContractError("Unsupported or duplicate opcode definition")
    sizes = {"h2c": (HIDDEN + 2 * KV_DIM) * 2, "c2h": HIDDEN * 2}
    if sizes != {"h2c": H2C_PAYLOAD_BYTES, "c2h": C2H_PAYLOAD_BYTES}:
        raise ContractError("Model dimensions disagree with payload sizes")
    if MODEL["q_heads"] * MODEL["head_dim"] != HIDDEN or MODEL["kv_heads"] * MODEL["head_dim"] != KV_DIM:
        raise ContractError("Head dimensions disagree with model")
    if MODEL["q_heads"] != 3 * MODEL["kv_heads"]:
        raise ContractError("Unsupported GQA grouping")
    for direction, size in sizes.items():
        if _CONTRACT["payloads"][f"{direction}_total_bytes"] != HEADER_BYTES + size:
            raise ContractError("Total frame size disagrees with JSON")
    for name in _OP_NAMES.values():
        expected_sizes = {"h2c": 0, "c2h": 0} if name == "reset_cache" else sizes
        if _CONTRACT["operation_payload_bytes"][name] != expected_sizes:
            raise ContractError("Opcode payload sizes disagree with profile")
    if _CRC_SIZE != 4 or _CRC_FIELD["type"] != "u32":
        raise ContractError("Unsupported checksum field")


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
    crc32: int

    def check(self, *, direction: str, op: int | None = None) -> None:
        if direction not in ("h2c", "c2h"):
            raise ContractError("Direction must be h2c or c2h")
        for field in HEADER_LAYOUT:
            if field["type"] == "zero_bytes":
                continue
            value = getattr(self, field["field"])
            if type(value) is not int or not 0 <= value < 1 << (8 * field["size"]):
                raise ContractError(f"Invalid {field['field']}: {value!r}")
        if self.magic != MAGIC or self.version != PROTOCOL_VERSION:
            raise ContractError("Magic/version mismatch; legacy v1 is unsupported")
        if self.op not in _OP_NAMES or (op is not None and self.op != op):
            raise ContractError(f"Unsupported/unexpected opcode: {self.op}")
        if self.flags != 0:
            raise ContractError("All flags are reserved and must be zero")
        if not SEQ_MIN <= self.seq <= SEQ_MAX:
            raise ContractError("Sequence must be a nonzero uint32")
        expected = _CONTRACT["operation_payload_bytes"][_OP_NAMES[self.op]][direction]
        if self.payload_len != expected:
            raise ContractError(f"{direction} payload_len must be {expected}, got {self.payload_len}")
        if self.op == OP_RESET_CACHE:
            if self.layer != GLOBAL_LAYER or self.position != 0:
                raise ContractError("Reset must use global layer sentinel and position zero")
        elif not 0 <= self.layer < LAYERS or not 0 <= self.position < CONTEXT:
            raise ContractError("Layer/position out of range")


_validate_schema()
if {field["field"] for field in HEADER_LAYOUT if field["type"] != "zero_bytes"} != {field.name for field in fields(Header)}:
    raise ContractError("Header dataclass fields disagree with JSON")


def pack_header(header: Header, *, direction: str) -> bytes:
    header.check(direction=direction)
    values = [bytes(field["size"]) if field["type"] == "zero_bytes" else getattr(header, field["field"])
              for field in HEADER_LAYOUT]
    return _HEADER.pack(*values)


def unpack_header(buf: bytes, *, direction: str) -> Header:
    if not isinstance(buf, bytes) or len(buf) != HEADER_BYTES:
        raise ContractError(f"Header must be exactly {HEADER_BYTES} bytes")
    values = {}
    for field, value in zip(HEADER_LAYOUT, _HEADER.unpack(buf)):
        if field["type"] == "zero_bytes":
            if value != bytes(field["size"]):
                raise ContractError(f"Nonzero {field['field']}")
        else:
            values[field["field"]] = value
    header = Header(**values)
    header.check(direction=direction)
    return header


def _frame_crc(raw_header: bytes, payload: bytes) -> int:
    cleared = raw_header[:_CRC_OFFSET] + bytes(_CRC_SIZE) + raw_header[_CRC_OFFSET + _CRC_SIZE:]
    return crc32(cleared + payload)


def _pack_frame(seq: int, layer: int, position: int, payload: bytes, *, op: int, flags: int, direction: str) -> bytes:
    if not isinstance(payload, bytes):
        raise ContractError("Payload must be bytes (not an implicit tensor conversion)")
    header = Header(MAGIC, PROTOCOL_VERSION, op, flags, layer, position, seq, len(payload), 0)
    raw = pack_header(header, direction=direction)
    header = replace(header, crc32=_frame_crc(raw, payload))
    return pack_header(header, direction=direction) + payload


def pack_request(seq: int, layer: int, position: int, payload: bytes, *, op: int = OP_ATTENTION, flags: int = 0) -> bytes:
    """No implicit reset at position=0. Use pack_reset once per new prompt."""
    return _pack_frame(seq, layer, position, payload, op=op, flags=flags, direction="h2c")


def pack_response(seq: int, layer: int, position: int, payload: bytes, *, op: int = OP_ATTENTION, flags: int = 0) -> bytes:
    """Reference encoder for testbench/golden responses; no hardware execution."""
    return _pack_frame(seq, layer, position, payload, op=op, flags=flags, direction="c2h")


def _unpack_frame(frame: bytes, *, direction: str) -> tuple[Header, bytes]:
    if not isinstance(frame, bytes) or len(frame) < HEADER_BYTES:
        raise ContractError("Truncated/non-bytes frame")
    header = unpack_header(frame[:HEADER_BYTES], direction=direction)
    if len(frame) != HEADER_BYTES + header.payload_len:
        raise ContractError("Frame length disagrees with validated header; trailing padding is not a frame")
    payload = frame[HEADER_BYTES:]
    if _frame_crc(frame[:HEADER_BYTES], payload) != header.crc32:
        raise ContractError("CRC32 mismatch (header and payload are protected)")
    return header, payload


def unpack_request(frame: bytes) -> tuple[Header, bytes]:
    return _unpack_frame(frame, direction="h2c")


def unpack_response(frame: bytes, *, expect_seq: int, expect_layer: int, expect_position: int,
                    expect_op: int = OP_ATTENTION) -> tuple[Header, bytes]:
    # Validate caller expectations too: bools, invalid op and ranges are errors.
    if type(expect_op) is not int or expect_op not in _OP_NAMES:
        raise ContractError("Invalid expected opcode")
    size = _CONTRACT["operation_payload_bytes"][_OP_NAMES[expect_op]]["c2h"]
    Header(MAGIC, PROTOCOL_VERSION, expect_op, 0, expect_layer, expect_position, expect_seq, size, 0).check(direction="c2h")
    header, payload = _unpack_frame(frame, direction="c2h")
    if (header.seq, header.layer, header.position, header.op) != (expect_seq, expect_layer, expect_position, expect_op):
        raise ContractError("Response seq/layer/position/op mismatch; stale response is not consumable")
    return header, payload


def pack_reset(seq: int) -> bytes:
    return pack_request(seq, GLOBAL_LAYER, 0, b"", op=OP_RESET_CACHE)


def unpack_reset_response(frame: bytes, *, expect_seq: int) -> Header:
    header, _ = unpack_response(frame, expect_seq=expect_seq, expect_layer=GLOBAL_LAYER,
                                expect_position=0, expect_op=OP_RESET_CACHE)
    return header


def make_test_payload(counter: int) -> bytes:
    if type(counter) is not int or not 0 <= counter <= SEQ_MAX:
        raise ContractError("Test counter must be uint32")
    count = _CONTRACT["test_pattern"]["counter_bytes"]
    return counter.to_bytes(count, "little") + bytes((counter + i) & 255 for i in range(count, H2C_PAYLOAD_BYTES))


def test_response_payload(payload: bytes) -> bytes:
    if not isinstance(payload, bytes) or len(payload) != H2C_PAYLOAD_BYTES:
        raise ContractError("Test request must have exact H2C size")
    return payload[:C2H_PAYLOAD_BYTES]


def pack_f16(values) -> bytes:
    try:
        values = tuple(float(value) for value in values)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Non-finite tensor")
        return struct.pack(f"<{len(values)}e", *values)
    except (TypeError, ValueError, OverflowError, struct.error) as exc:
        raise ContractError(f"Invalid FP16 values: {exc}") from exc


def unpack_f16(payload: bytes) -> tuple[float, ...]:
    if not isinstance(payload, bytes) or len(payload) % 2:
        raise ContractError("FP16 payload must be bytes with even length")
    values = struct.unpack(f"<{len(payload) // 2}e", payload)
    if any(not math.isfinite(value) for value in values):
        raise ContractError("Non-finite FP16 payload")
    return values


def _self_test() -> None:
    if crc32(b"123456789") != 0xCBF43926:
        raise ContractError("CRC known-answer failure")
    payload = make_test_payload(7)
    header, decoded = unpack_request(pack_request(7, 3, 0, payload, op=OP_TEST))
    if decoded != payload or header.flags != 0:
        raise ContractError("Test request round-trip failure")
    response = pack_response(7, 3, 0, test_response_payload(payload), op=OP_TEST)
    unpack_response(response, expect_seq=7, expect_layer=3, expect_position=0, expect_op=OP_TEST)
    ack = pack_response(8, GLOBAL_LAYER, 0, b"", op=OP_RESET_CACHE)
    unpack_reset_response(ack, expect_seq=8)
    print("contract v2 self-test OK (PC codec only; NO board/Gate evidence)")


if __name__ == "__main__":
    _self_test()
