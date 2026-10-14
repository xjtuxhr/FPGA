"""PC-only tests for the single-layer ATTENTION runner helpers (no board).

Exercises request packing, golden loading/comparison and the transport
ATTENTION framing path against the in-memory mock. These are NOT board Gate
evidence.
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport import attention_vectors as av
from pcie_transport.binding import Binding, KIND_MOCK
from pcie_transport.tests.mock_device import MockDevice
from pcie_transport.transport import Transport, TransportError
from pcie_transport.tools.run_attention_on_board import build_cases, summarize


def mock_binding() -> Binding:
    return Binding(
        kind=KIND_MOCK, binding_version=1, contract_version=2,
        evidence_ref="mock (PC-only)", bdf="mock:00.0", vendor_device="1edb:abcd",
        bound_driver="mock", bars="mock", h2c_node="/dev/mock_h2c",
        c2h_node="/dev/mock_c2h", control_node="/dev/mock_ctrl",
        access_method="mock", address_formula="mock", data_mode="mock",
        dma_alignment="1", dma_length_granularity="1", submit_order="mock",
        dma_completion="mock", attention_completion="mock",
        timeout_handling="finite deadline", clock_method="time.monotonic",
    )


class PatternTests(unittest.TestCase):
    def test_pattern_lengths_and_pack(self):
        q, k, v = av.build_pattern_qkv(0)
        self.assertEqual((len(q), len(k), len(v)), (c.HIDDEN, c.KV_DIM, c.KV_DIM))
        payload = av.pack_qkv(q, k, v)
        self.assertEqual(len(payload), c.H2C_PAYLOAD_BYTES)

    def test_pack_qkv_rejects_wrong_lengths(self):
        with self.assertRaises(ValueError):
            av.pack_qkv((0.0,) * 10, (0.0,) * c.KV_DIM, (0.0,) * c.KV_DIM)


class CompareTests(unittest.TestCase):
    def _frame(self, payload: bytes) -> bytes:
        return c.pack_response(3, 0, 0, payload, op=c.OP_ATTENTION)

    def test_match(self):
        out = [0.5] * c.HIDDEN
        frame = self._frame(c.pack_f16(out))
        result = av.compare_output(frame, out)
        self.assertTrue(result["match"])
        self.assertEqual(result["bad"], 0)

    def test_mismatch(self):
        frame = self._frame(c.pack_f16([0.0] * c.HIDDEN))
        result = av.compare_output(frame, [1.0] * c.HIDDEN)
        self.assertFalse(result["match"])
        self.assertEqual(result["bad"], c.HIDDEN)

    def test_nonfinite_reported(self):
        payload = struct.pack("<e", float("inf")) * c.HIDDEN
        frame = self._frame(payload)
        result = av.compare_output(frame, [0.0] * c.HIDDEN)
        self.assertTrue(result["nonfinite"])
        self.assertFalse(result["match"])


class GoldenTests(unittest.TestCase):
    def test_load_golden_ok(self):
        case = {"layer": 1, "position": 2,
                "q": [0.0] * c.HIDDEN, "k": [0.0] * c.KV_DIM, "v": [0.0] * c.KV_DIM,
                "output": [0.0] * c.HIDDEN}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.json"
            p.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
            cases = av.load_golden(p)
            self.assertEqual(len(cases), 1)

    def test_load_golden_bad(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.json"
            p.write_text(json.dumps({"cases": [{"layer": 0}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                av.load_golden(p)


class BuildCasesTests(unittest.TestCase):
    def test_pattern_cases(self):
        cases = build_cases(3, 5, 10, None)
        self.assertEqual([x["position"] for x in cases], [10, 11, 12])
        self.assertTrue(all(x["layer"] == 5 for x in cases))
        self.assertTrue(all(len(x["q"]) == c.HIDDEN for x in cases))


class SummarizeTests(unittest.TestCase):
    def test_summarize(self):
        out = summarize([0.01, 0.02, 0.03], framing_ok=3, compared=0, matched=0,
                        max_abs=0.0, nonfinite=0, profile="x")
        self.assertEqual(out["rounds"], 3)
        self.assertEqual(out["errors"], 0)
        self.assertIn("p95_s", out)


class TransportAttentionTests(unittest.TestCase):
    def test_attention_framing_via_mock(self):
        transport = Transport(MockDevice(), mock_binding())
        transport.reset_cache(timeout_s=5.0)
        q, k, v = av.build_pattern_qkv(0)
        response, timing = transport.round_trip(c.OP_ATTENTION, 0, 0,
                                                av.pack_qkv(q, k, v), timeout_s=5.0)
        self.assertEqual(len(response), c.HEADER_BYTES + c.C2H_PAYLOAD_BYTES)
        self.assertGreaterEqual(timing.total_s, 0.0)

    def test_attention_requires_reset(self):
        transport = Transport(MockDevice(), mock_binding())
        q, k, v = av.build_pattern_qkv(0)
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_ATTENTION, 0, 0, av.pack_qkv(q, k, v), timeout_s=5.0)


if __name__ == "__main__":
    unittest.main()
