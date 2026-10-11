"""PC-only tests for the host transport plugin (exchange/close/metadata).

Uses the in-memory mock device; opens no device and is NOT board evidence.
Covers the accurate capability declaration and the negative paths that must
fail closed: short write, missing completion (timeout), stale frame and CRC
corruption (the last two surface to the host's contract verification).
"""
import unittest

from pcie_contract import contract as c
from pcie_transport import binding as b
from pcie_transport.host_plugin import BoardTransport
from pcie_transport.tests.mock_device import Faults, MockDevice
from pcie_transport.transport import TransportError


def mock_binding() -> b.Binding:
    return b.Binding(
        kind=b.KIND_MOCK, binding_version=1, contract_version=2,
        evidence_ref="unit-test fixture", bdf="test:00.0",
        vendor_device="1edb:abcd", bound_driver="mock",
        h2c_node="/dev/mock_h2c", c2h_node="/dev/mock_c2h", control_node="/dev/mock_ctrl",
        access_method="mock", data_mode="mock", dma_alignment="1",
        dma_length_granularity="1", submit_order="mock", dma_completion="mock",
        attention_completion="mock", timeout_handling="finite monotonic deadline",
        clock_method="time.monotonic (PC only)",
    )


def make(faults=None):
    return BoardTransport(MockDevice(faults or Faults()), mock_binding())


class HostPluginMetadataTests(unittest.TestCase):
    def test_metadata_declares_only_verified_capability(self):
        md = make().metadata()
        self.assertEqual(md["protocol_version"], 2)
        self.assertEqual(md["wire_dtype"], "fp16_le")
        self.assertEqual(md["max_inflight"], 1)
        self.assertTrue(md["hardware_transport"])
        self.assertTrue(md["binding_verified"])
        # Unimplemented capabilities must read False:
        self.assertFalse(md["attention_supported"])
        self.assertFalse(md["policy_configured"])
        self.assertFalse(md["kv_write_supported"])
        self.assertEqual(md["supported_ops"], ["reset_cache", "test"])


class HostPluginExchangeTests(unittest.TestCase):
    def test_reset_then_test_round_trip(self):
        t = make()
        ack = t.exchange(c.pack_reset(1), timeout_s=2.0)
        c.unpack_reset_response(ack, expect_seq=1)
        payload = c.make_test_payload(5)
        response = t.exchange(c.pack_request(2, 1, 0, payload, op=c.OP_TEST), timeout_s=2.0)
        _, decoded = c.unpack_response(response, expect_seq=2, expect_layer=1,
                                        expect_position=0, expect_op=c.OP_TEST)
        self.assertEqual(decoded, c.test_response_payload(payload))

    def test_short_write_fails_closed(self):
        t = make(Faults(short_write=True))
        with self.assertRaises(TransportError):
            t.exchange(c.pack_reset(1), timeout_s=1.0)

    def test_missing_completion_times_out(self):
        t = make(Faults(drop_completion=True))
        with self.assertRaises(TransportError):
            t.exchange(c.pack_request(1, 0, 0, c.make_test_payload(1), op=c.OP_TEST), timeout_s=1.0)

    def test_stale_frame_surfaces_to_host_verification(self):
        # The plugin performs transport I/O only; a stale frame must be rejected
        # by the host's contract check, proving it is not silently accepted.
        t = make(Faults(stale_response=True))
        t.exchange(c.pack_reset(1), timeout_s=1.0)
        response = t.exchange(c.pack_request(2, 0, 0, c.make_test_payload(1), op=c.OP_TEST), timeout_s=1.0)
        with self.assertRaises(c.ContractError):
            c.unpack_response(response, expect_seq=2, expect_layer=0,
                              expect_position=0, expect_op=c.OP_TEST)

    def test_crc_corruption_surfaces_to_host_verification(self):
        t = make(Faults(corrupt_frame=True))
        t.exchange(c.pack_reset(1), timeout_s=1.0)
        response = t.exchange(c.pack_request(2, 0, 0, c.make_test_payload(1), op=c.OP_TEST), timeout_s=1.0)
        with self.assertRaises(c.ContractError):
            c.unpack_response(response, expect_seq=2, expect_layer=0,
                              expect_position=0, expect_op=c.OP_TEST)

    def test_closed_transport_rejects(self):
        t = make()
        t.close()
        with self.assertRaises(TransportError):
            t.exchange(c.pack_reset(1), timeout_s=1.0)


if __name__ == "__main__":
    unittest.main()
