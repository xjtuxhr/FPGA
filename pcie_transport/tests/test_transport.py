"""Transport state machine and binding-guard tests (PC only, mock device).

These verify logic and fail-closed behavior. They never open devices, never
touch BARs, and never claim board latency.
"""
import json
import time
import unittest
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport import binding as b
from pcie_transport.transport import Transport, TransportError, State
from pcie_transport.tests.mock_device import Faults, MockDevice


def valid_binding() -> b.Binding:
    return b.Binding(
        binding_version=1, contract_version=2, evidence_ref="unit-test fixture",
        bdf="test:00.0", vendor_device="1edb:abcd", bound_driver="mock",
        h2c_node="/dev/mock_h2c", c2h_node="/dev/mock_c2h", control_node="/dev/mock_ctrl",
        access_method="mock", data_mode="mock", dma_alignment="1",
        dma_length_granularity="1", submit_order="mock", dma_completion="mock",
        attention_completion="mock", timeout_handling="finite monotonic deadline",
        clock_method="time.monotonic (PC only)",
    )


def make_transport(faults=None):
    return Transport(MockDevice(faults or Faults()), valid_binding())


class BindingTests(unittest.TestCase):
    def test_incomplete_binding_refused(self):
        incomplete = b.Binding(binding_version=1, contract_version=2, bdf="test:00.0")
        self.assertFalse(incomplete.is_bound)

    def test_load_rejects_missing_file_and_bad_contract(self):
        with self.assertRaises(b.BindingError):
            b.Binding.load(Path("/nonexistent/binding.json"))
        tmp = Path("binding_tmp_test.json")
        data = json.loads(json.dumps({
            "binding_version": 1, "contract_version": 1, "bdf": "t:00.0",
            "vendor_device": "1edb:abcd", "h2c_node": "/dev/x", "c2h_node": "/dev/y",
            "control_node": "/dev/z", "access_method": "m", "data_mode": "m",
            "dma_alignment": "1", "dma_length_granularity": "1", "submit_order": "m",
            "dma_completion": "m", "attention_completion": "m",
            "timeout_handling": "m", "clock_method": "m",
        }))
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(b.BindingError):
                b.Binding.load(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_load_rejects_wrong_device(self):
        tmp = Path("binding_tmp_test.json")
        data = {k: getattr(valid_binding(), k) for k in valid_binding().__dataclass_fields__}
        data["vendor_device"] = "dead:beef"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(b.BindingError):
                b.Binding.load(tmp)
        finally:
            tmp.unlink(missing_ok=True)


class TransportTests(unittest.TestCase):
    def test_unbound_transport_refuses_to_run(self):
        with self.assertRaises(b.BindingError):
            Transport(MockDevice(), None)

    def test_reset_then_attention_roundtrip(self):
        transport = make_transport()
        transport.reset_cache()
        payload = c.make_test_payload(11)
        response, timing = transport.round_trip(c.OP_TEST, 2, 5, payload)
        self.assertEqual(response[c.HEADER_BYTES:], c.test_response_payload(payload))
        self.assertGreaterEqual(timing.total_s, 0.0)
        self.assertEqual(transport.state, State.IDLE)

    def test_reset_ack_and_state_return(self):
        transport = make_transport()
        transport.reset_cache()
        self.assertEqual(transport.state, State.IDLE)

    def test_seq_strictly_increases(self):
        transport = make_transport()
        transport.reset_cache()
        first = transport.next_seq
        transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1))
        second = transport.next_seq
        transport.round_trip(c.OP_TEST, 0, 1, c.make_test_payload(2))
        self.assertGreater(second, first)
        self.assertGreater(transport.next_seq, second)

    def test_position_zero_does_not_implicitly_reset(self):
        transport = make_transport()
        transport.reset_cache()
        # A plain attention/test at position 0 must not be a reset op.
        payload = c.make_test_payload(3)
        frame = c.pack_request(1, 0, 0, payload, op=c.OP_TEST)
        header, _ = c.unpack_request(frame)
        self.assertEqual(header.op, c.OP_TEST)
        self.assertEqual(header.layer, 0)
        self.assertEqual(header.flags, 0)

    def test_single_inflight_enforced(self):
        transport = make_transport(Faults(drop_completion=True))
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.2)
        self.assertEqual(transport.state, State.FAULT)
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 1, c.make_test_payload(2), timeout_s=0.2)

    def test_stale_frame_causes_fault(self):
        transport = make_transport(Faults(stale_response=True))
        transport.reset_cache()
        transport.device.faults.stale_response = False
        # re-arm after the clean reset so only the round trip sees the stale frame
        transport.device.faults.stale_response = True
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.5)
        self.assertEqual(transport.state, State.FAULT)

    def test_corrupt_frame_causes_fault(self):
        transport = make_transport()
        transport.reset_cache()
        transport.device.faults.corrupt_frame = True
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.5)
        self.assertEqual(transport.state, State.FAULT)

    def test_recover_flushes_and_requires_reset_first(self):
        transport = make_transport(Faults(drop_completion=True))
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.2)
        device = transport.device
        device.faults.drop_completion = False
        transport.recover()
        self.assertEqual(transport.state, State.IDLE)
        self.assertGreaterEqual(device.flushes, 1)
        transport.reset_cache()
        transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(2))

    def test_reset_while_inflight_rejected(self):
        transport = make_transport(Faults(drop_completion=True))
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.2)
        with self.assertRaises(TransportError):
            transport.reset_cache()

    def test_short_read_rejected(self):
        transport = make_transport(Faults(short_read=True))
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.5)
        self.assertEqual(transport.state, State.FAULT)


if __name__ == "__main__":
    unittest.main()
