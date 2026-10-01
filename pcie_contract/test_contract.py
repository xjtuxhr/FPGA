"""PC-only contract regression. Never opens devices or exercises real DMA."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import unittest

from pcie_contract import contract as c


def bitwise_crc32(data):
    """Independent, slow reflected IEEE reference (no zlib or codec calls)."""
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xEDB88320 if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def mutate(frame, offset, raw, *, repair_crc=False):
    data = bytearray(frame)
    data[offset:offset + len(raw)] = raw
    if repair_crc:
        data[24:28] = bytes(4)
        data[24:28] = struct.pack("<I", bitwise_crc32(data))
    return bytes(data)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.input = bytes(c.H2C_PAYLOAD_BYTES)
        self.output = bytes(c.C2H_PAYLOAD_BYTES)
        self.request = c.pack_request(7, 3, 128, self.input)
        self.response = c.pack_response(7, 3, 128, self.output)

    def decode(self, frame, **changes):
        expected = dict(expect_seq=7, expect_layer=3, expect_position=128)
        expected.update(changes)
        return c.unpack_response(frame, **expected)

    def test_crc_known_answer_and_independent_reference(self):
        for data in (b"", b"123456789", bytes(range(256)), self.request):
            with self.subTest(length=len(data)):
                self.assertEqual(c.crc32(data), bitwise_crc32(data))
        self.assertEqual(c.crc32(b"123456789"), 0xCBF43926)
        self.assertNotEqual(c.crc32(b"123456789"), 0xE3069283)

    def test_magic_little_endian_and_version(self):
        self.assertEqual(self.request[:4], b"KVMX")
        self.assertEqual(self.request[4:6], b"\x02\x00")

    def test_header_generated_from_json(self):
        self.assertEqual(struct.calcsize(c.HEADER_FMT), 32)
        self.assertEqual(c._CRC_OFFSET, 24)
        self.assertEqual(self.request[9:12] + self.request[22:24] + self.request[28:32], bytes(9))
        header = c.unpack_header(self.request[:32], direction="h2c")
        self.assertEqual(c.pack_header(header, direction="h2c"), self.request[:32])

    def test_attention_request_response(self):
        header, payload = c.unpack_request(self.request)
        self.assertEqual((header.seq, header.layer, header.position), (7, 3, 128))
        self.assertEqual(payload, self.input)
        header, payload = self.decode(self.response)
        self.assertEqual(header.payload_len, 1152)
        self.assertEqual(payload, self.output)

    def test_reset_empty_request_and_ack(self):
        request = c.pack_reset(8)
        self.assertEqual(len(request), 32)
        header, payload = c.unpack_request(request)
        self.assertEqual((header.op, header.layer, header.position, payload), (c.OP_RESET_CACHE, 255, 0, b""))
        ack = c.pack_response(8, 255, 0, b"", op=c.OP_RESET_CACHE)
        self.assertEqual(c.unpack_reset_response(ack, expect_seq=8).seq, 8)
        with self.assertRaises(c.ContractError):
            c.unpack_reset_response(ack, expect_seq=9)

    def test_position_zero_never_implicitly_resets(self):
        for layer in (0, 3, 29):
            header, _ = c.unpack_request(c.pack_request(1, layer, 0, self.input))
            self.assertEqual((header.op, header.flags), (c.OP_ATTENTION, 0))

    def test_reset_rejects_layer_position_payload(self):
        for layer, position, payload in ((0, 0, b""), (255, 1, b""), (255, 0, self.input)):
            with self.subTest(layer=layer, position=position), self.assertRaises(c.ContractError):
                c.pack_request(1, layer, position, payload, op=c.OP_RESET_CACHE)

    def test_request_rejects_invalid_arguments(self):
        defaults = dict(seq=7, layer=3, position=128, payload=self.input)
        invalid = [
            {"seq": 0}, {"seq": -1}, {"seq": 2**32}, {"seq": True},
            {"layer": -1}, {"layer": 30}, {"layer": 255}, {"layer": 3.0},
            {"position": -1}, {"position": 2048}, {"position": 2**32},
            {"op": 99}, {"op": True}, {"flags": 1}, {"flags": -1},
            {"payload": bytearray(self.input)},
        ]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(c.ContractError):
                c.pack_request(**(defaults | change))

    def test_exact_request_and_response_payload_lengths(self):
        for length in (0, 1152, 1919, 1921):
            with self.subTest(direction="h2c", length=length), self.assertRaises(c.ContractError):
                c.pack_request(1, 0, 0, bytes(length))
        for length in (0, 1151, 1153, 1920):
            with self.subTest(direction="c2h", length=length), self.assertRaises(c.ContractError):
                c.pack_response(1, 0, 0, bytes(length))

    def test_header_rejects_wrong_direction_and_invalid_scalar(self):
        header = c.unpack_header(self.request[:32], direction="h2c")
        for direction in ("wrong", "c2h"):
            with self.subTest(direction=direction), self.assertRaises(c.ContractError):
                header.check(direction=direction)
        for change in ({"crc32": -1}, {"crc32": 2**32}, {"version": 1}, {"magic": 0}):
            with self.subTest(change=change), self.assertRaises(c.ContractError):
                c.pack_header(replace(header, **change), direction="h2c")

    def test_bad_wire_fields_rejected_even_with_valid_crc(self):
        cases = [
            (0, b"XMVK"), (4, struct.pack("<H", 1)), (6, b"\x63"),
            (7, b"\x01"), (8, b"\x1e"), (9, b"\x01"),
            (12, struct.pack("<I", 2048)), (16, bytes(4)),
            (20, bytes(2)), (20, struct.pack("<H", 1920)),
            (22, b"\x01"), (28, b"\x01"),
        ]
        for offset, raw in cases:
            with self.subTest(offset=offset, raw=raw), self.assertRaises(c.ContractError):
                self.decode(mutate(self.response, offset, raw, repair_crc=True))

    def test_response_identity_mismatch(self):
        for change in ({"expect_seq": 8}, {"expect_layer": 4}, {"expect_position": 129}, {"expect_op": c.OP_TEST}):
            with self.subTest(change=change), self.assertRaises(c.ContractError):
                self.decode(self.response, **change)

    def test_invalid_response_expectations(self):
        for change in ({"expect_seq": 0}, {"expect_seq": True}, {"expect_layer": 30},
                       {"expect_position": 2048}, {"expect_op": 99}, {"expect_op": True}):
            with self.subTest(change=change), self.assertRaises(c.ContractError):
                self.decode(self.response, **change)

    def test_truncated_or_trailing_frames(self):
        for frame in (b"", self.response[:1], self.response[:31], self.response[:32],
                      self.response[:-1], self.response + b"\x00", self.response + bytes(32)):
            with self.subTest(length=len(frame)), self.assertRaises(c.ContractError):
                self.decode(frame)
        with self.assertRaises(c.ContractError):
            c.unpack_header(self.response[:31], direction="c2h")
        with self.assertRaises(c.ContractError):
            c.unpack_request(bytearray(self.request))

    def test_crc_protects_header_and_payload(self):
        # Valid semantic changes still fail without a recomputed CRC.
        for offset, raw in ((8, b"\x04"), (12, struct.pack("<I", 129)), (32, b"\x01"), (24, b"\xff")):
            with self.subTest(offset=offset), self.assertRaises(c.ContractError):
                self.decode(mutate(self.response, offset, raw))

    def test_test_pattern_and_asymmetric_oracle(self):
        payload = c.make_test_payload(0x01020304)
        self.assertEqual(payload[:4], b"\x04\x03\x02\x01")
        self.assertEqual(payload[4:8], bytes([8, 9, 10, 11]))
        self.assertEqual(c.test_response_payload(payload), payload[:1152])
        for counter in (-1, 2**32, True):
            with self.subTest(counter=counter), self.assertRaises(c.ContractError):
                c.make_test_payload(counter)
        with self.assertRaises(c.ContractError):
            c.test_response_payload(b"")

    def test_30_codec_round_trips_not_hardware_gate(self):
        for counter in range(30):
            payload = c.make_test_payload(counter)
            frame = c.pack_request(counter + 1, counter, 0, payload, op=c.OP_TEST)
            header, received = c.unpack_request(frame)
            response = c.pack_response(header.seq, header.layer, header.position,
                                       c.test_response_payload(received), op=c.OP_TEST)
            _, actual = c.unpack_response(response, expect_seq=counter + 1, expect_layer=counter,
                                          expect_position=0, expect_op=c.OP_TEST)
            self.assertEqual(actual, payload[:1152])

    def test_f16_round_trip_and_signed_zero(self):
        values = [0.0, -0.0, 0.25, -0.5, 1.0, 2.5, 65504.0]
        payload = c.pack_f16(values)
        self.assertEqual(c.unpack_f16(payload), tuple(values))
        self.assertEqual(payload[:4], b"\x00\x00\x00\x80")
        self.assertEqual(c.pack_f16([]), b"")
        self.assertEqual(c.unpack_f16(b""), ())

    def test_f16_rejects_nonfinite_overflow_and_odd_bytes(self):
        for values in ([float("nan")], [float("inf")], [-float("inf")], [1e10], ["not_float"], None):
            with self.subTest(values=values), self.assertRaises(c.ContractError):
                c.pack_f16(values)
        for payload in (b"\x00", b"\x00\x7c", b"\x00\xfc", b"\x01\x7e"):
            with self.subTest(payload=payload), self.assertRaises(c.ContractError):
                c.unpack_f16(payload)

    def test_schema_changes_fail_closed(self):
        mutations = [
            ("magic_hex", "0x4B564D58"),
            ("flags_allowed", 1),
            ("max_inflight", 2),
            ("wire_dtype", "int8"),
            ("checksum", c._CONTRACT["checksum"] | {"name": "CRC32C"}),
            ("payloads", c._CONTRACT["payloads"] | {"c2h_total_bytes": 1185}),
        ]
        for key, value in mutations:
            original = c._CONTRACT[key]
            try:
                c._CONTRACT[key] = value
                with self.subTest(key=key), self.assertRaises(c.ContractError):
                    c._validate_schema()
            finally:
                c._CONTRACT[key] = original

    def test_invalid_json_layout(self):
        original = c.HEADER_LAYOUT
        try:
            for change in ({"offset": 1}, {"size": 3}, {"type": "float"}):
                modified = copy.deepcopy(original)
                modified[0].update(change)
                c.HEADER_LAYOUT = modified
                with self.subTest(change=change), self.assertRaises(c.ContractError):
                    c._make_header_struct()
        finally:
            c.HEADER_LAYOUT = original

    def test_fixed_golden_headers_frames_and_independent_crc(self):
        fixture = json.loads(Path(__file__).with_name("golden_vectors.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["protocol_version"], c.PROTOCOL_VERSION)
        for vector in fixture["vectors"]:
            with self.subTest(name=vector["name"]):
                length = vector["payload_bytes"]
                if vector["pattern"] == "zeros":
                    payload = bytes(length)
                else:
                    counter = vector["counter"]
                    payload = struct.pack("<I", counter) + bytes((counter + i) & 255 for i in range(4, 1920))
                    payload = payload[:length]
                encoder = c.pack_request if vector["direction"] == "h2c" else c.pack_response
                frame = encoder(vector["seq"], vector["layer"], vector["position"], payload, op=vector["op"])
                self.assertEqual(frame[:32].hex(), vector["header_hex"])
                self.assertEqual(hashlib.sha256(frame).hexdigest(), vector["frame_sha256"])
                zeroed = frame[:24] + bytes(4) + frame[28:]
                self.assertEqual(struct.unpack_from("<I", frame, 24)[0], bitwise_crc32(zeroed))
                if vector["direction"] == "h2c":
                    _, decoded = c.unpack_request(frame)
                else:
                    _, decoded = c.unpack_response(frame, expect_seq=vector["seq"], expect_layer=vector["layer"],
                                                    expect_position=vector["position"], expect_op=vector["op"])
                self.assertEqual(decoded, payload)


if __name__ == "__main__":
    unittest.main()
