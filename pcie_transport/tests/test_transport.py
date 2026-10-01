"""Transport state machine and binding-guard tests (PC only, mock device).

These verify logic and fail-closed behavior. They never open devices, never
touch BARs, and never claim board latency.
"""
import json
import threading
import time
import unittest
from dataclasses import asdict
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport import binding as b
from pcie_transport.transport import Transport, TransportError, State
from pcie_transport.tests.mock_device import Faults, MockDevice


def valid_binding() -> b.Binding:
    return b.Binding(
        kind=b.KIND_MOCK, binding_version=1, contract_version=2,
        evidence_ref="unit-test fixture",
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
        incomplete = b.Binding(kind=b.KIND_REAL, binding_version=1, contract_version=2,
                               vendor_device="1edb:abcd", bdf="test:00.0")
        self.assertFalse(incomplete.is_bound)

    def test_construction_validates_protocol_invariants(self):
        with self.assertRaises(b.BindingError):
            b.Binding(kind=b.KIND_MOCK, binding_version=1, contract_version=1,
                      vendor_device="1edb:abcd", bdf="t:00.0")
        with self.assertRaises(b.BindingError):
            b.Binding(kind=b.KIND_MOCK, binding_version=1, contract_version=2,
                      vendor_device="dead:beef", bdf="t:00.0")
        with self.assertRaises(b.BindingError):
            b.Binding(kind="nonsense", binding_version=1, contract_version=2,
                      vendor_device="1edb:abcd", bdf="t:00.0")
        with self.assertRaises(b.BindingError):
            b.Binding(kind=b.KIND_MOCK, binding_version=0, contract_version=2,
                      vendor_device="1edb:abcd", bdf="t:00.0")

    def test_transport_rejects_bypassed_invalid_binding(self):
        # Even if someone builds the object with empty evidence fields the
        # constructor rejects protocol-level violations; Transport still
        # refuses anything that is not complete bound evidence.
        bogus = b.Binding(kind=b.KIND_REAL, binding_version=1, contract_version=2,
                          vendor_device="1edb:abcd", bdf="t:00.0")
        with self.assertRaises(b.BindingError):
            Transport(MockDevice(), bogus)

    def test_real_binding_requires_evidence_fields(self):
        # Core fields all filled, but the four handover-evidence fields empty:
        # must NOT count as bound, and Transport/load/save must all refuse.
        base = {name: getattr(valid_binding(), name)
                for name in valid_binding().__dataclass_fields__}
        for field_name in ("evidence_ref", "bound_driver", "bars", "address_formula"):
            base[field_name] = ""
        real = b.Binding(**{**base, "kind": b.KIND_REAL})
        self.assertFalse(real.is_bound)
        with self.assertRaises(b.BindingError):
            Transport(MockDevice(), real)
        with self.assertRaises(b.BindingError):
            real.save(Path("binding_tmp_test.json"))

        tmp = Path("binding_tmp_test.json")
        tmp.write_text(json.dumps(asdict(real)), encoding="utf-8")
        try:
            with self.assertRaises(b.BindingError):
                b.Binding.load(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_real_binding_with_evidence_accepted(self):
        real = b.Binding(
            kind=b.KIND_REAL, binding_version=1, contract_version=2,
            evidence_ref="board-log-001", bdf="01:00.0", vendor_device="1edb:abcd",
            bound_driver="anlogic_pci", bars="BAR0 0xf0000000 size 1M",
            h2c_node="/dev/ANLOGIC-PCI0_0", c2h_node="/dev/ANLOGIC-PCI0_1",
            control_node="/dev/ANLOGIC-PCI0_2", access_method="user 32-bit pread/pwrite",
            address_formula="user BAR base +0x80000",
            data_mode="AXI-MM", dma_alignment="4B",
            dma_length_granularity="4B", submit_order="H2C then C2H",
            dma_completion="driver IRQ", attention_completion="status poll",
            timeout_handling="finite monotonic deadline", clock_method="time.monotonic",
        )
        self.assertTrue(real.is_bound)

    def test_load_rejects_missing_file_and_bad_contract(self):
        with self.assertRaises(b.BindingError):
            b.Binding.load(Path("/nonexistent/binding.json"))
        tmp = Path("binding_tmp_test.json")
        data = json.loads(json.dumps({
            "kind": b.KIND_REAL, "binding_version": 1, "contract_version": 1,
            "bdf": "t:00.0", "vendor_device": "1edb:abcd", "h2c_node": "/dev/x",
            "c2h_node": "/dev/y", "control_node": "/dev/z", "access_method": "m",
            "data_mode": "m", "dma_alignment": "1", "dma_length_granularity": "1",
            "submit_order": "m", "dma_completion": "m", "attention_completion": "m",
            "timeout_handling": "m", "clock_method": "m",
        }))
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(b.BindingError):
                b.Binding.load(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_save_refuses_incomplete_binding(self):
        incomplete = b.Binding(kind=b.KIND_REAL, binding_version=1, contract_version=2,
                               vendor_device="1edb:abcd", bdf="t:00.0")
        with self.assertRaises(b.BindingError):
            incomplete.save(Path("binding_tmp_test.json"))


class TransportTests(unittest.TestCase):
    def test_unbound_transport_refuses_to_run(self):
        with self.assertRaises(b.BindingError):
            Transport(MockDevice(), None)

    def test_attention_blocked_until_reset_ack(self):
        transport = make_transport()
        payload = c.make_test_payload(1)
        with self.assertRaises(TransportError) as ctx:
            transport.round_trip(c.OP_ATTENTION, 0, 0, payload, timeout_s=0.5)
        self.assertIn("reset", str(ctx.exception))
        self.assertEqual(transport.state, State.IDLE)  # caller misuse, not FAULT
        transport.reset_cache()
        transport.round_trip(c.OP_ATTENTION, 0, 0, payload, timeout_s=0.5)
        self.assertEqual(transport.state, State.IDLE)

    def test_op_test_allowed_before_reset(self):
        # OP_TEST performs no Attention and appends no KV; it is allowed
        # before a reset, unlike OP_ATTENTION.
        transport = make_transport()
        response, _ = transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(9), timeout_s=0.5)
        self.assertEqual(response[c.HEADER_BYTES:], c.test_response_payload(c.make_test_payload(9)))

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

    def test_reentrant_second_request_rejected_without_fault(self):
        transport = make_transport(Faults(write_delay_s=0.4))
        errors = []

        def slow_request():
            try:
                transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=2.0)
            except TransportError as exc:
                errors.append(exc)

        thread = threading.Thread(target=slow_request)
        thread.start()
        time.sleep(0.05)  # first request is inside device.write
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 1, c.make_test_payload(2), timeout_s=2.0)
        thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(transport.state, State.IDLE)
        self.assertIsNone(transport.inflight)

    def test_stale_frame_causes_fault(self):
        transport = make_transport(Faults(stale_response=True))
        transport.reset_cache()
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

    def test_short_write_causes_fault(self):
        transport = make_transport(Faults(short_write=True))
        with self.assertRaises(TransportError):
            transport.reset_cache(timeout_s=0.5)
        self.assertEqual(transport.state, State.FAULT)

        transport2 = make_transport()
        transport2.reset_cache()
        transport2.device.faults.short_write = True
        with self.assertRaises(TransportError):
            transport2.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.5)
        self.assertEqual(transport2.state, State.FAULT)

    def test_timeout_must_be_finite(self):
        transport = make_transport()
        for bad in (float("inf"), float("nan"), 0.0, -1.0):
            with self.assertRaises(TransportError):
                transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=bad)
        self.assertEqual(transport.state, State.IDLE)  # rejected before occupying slot

    def test_recover_rearms_reset_requirement(self):
        transport = make_transport(Faults(drop_completion=True))
        with self.assertRaises(TransportError):
            transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.2)
        device = transport.device
        device.faults.drop_completion = False
        transport.recover()
        self.assertEqual(transport.state, State.IDLE)
        self.assertGreaterEqual(device.flushes, 1)
        # Attention must be refused until a valid reset ACK arrives again.
        with self.assertRaises(TransportError) as ctx:
            transport.round_trip(c.OP_ATTENTION, 0, 0, c.make_test_payload(2), timeout_s=0.5)
        self.assertIn("reset", str(ctx.exception))
        transport.reset_cache()
        transport.round_trip(c.OP_ATTENTION, 0, 0, c.make_test_payload(2), timeout_s=0.5)

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

    def test_notify_called_after_write(self):
        transport = make_transport()
        transport.reset_cache()
        before = transport.device.notifies
        transport.round_trip(c.OP_TEST, 0, 0, c.make_test_payload(1), timeout_s=0.5)
        self.assertEqual(transport.device.notifies, before + 1)


if __name__ == "__main__":
    unittest.main()
