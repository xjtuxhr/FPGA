"""PC guard tests for the board OP_TEST runner (no board access).

Verifies the runner is fail-closed (no incomplete binding, no fabricated
device) and that it wires binding + device + transport correctly when given a
complete real binding and a test device module. These are PC tests; a PASS is
not board evidence.
"""
import json
import tempfile
import unittest
from pathlib import Path

from pcie_transport.tools import run_op_test_on_board as runner

REAL_FIELDS = {
    "kind": "real",
    "binding_version": 1,
    "contract_version": 2,
    "evidence_ref": "test-only",
    "bdf": "0000:01:00.0",
    "vendor_device": "1edb:abcd",
    "bound_driver": "anlogic_sgdma",
    "bars": "bar0 128K",
    "h2c_node": "/dev/test_h2c",
    "c2h_node": "/dev/test_c2h",
    "control_node": "/dev/test_ctrl",
    "node_permissions": "rw",
    "access_method": "32bit pread/pwrite",
    "address_formula": "user offset 0x80000 + logical 0",
    "data_mode": "AXI-ST",
    "aximm_buffers": "",
    "axist_framing": "TLAST/TKEEP",
    "dma_alignment": "64",
    "dma_length_granularity": "4",
    "dma_max_length": "4096",
    "dma_padding": "none",
    "coherence_sync": "driver sync",
    "submit_order": "H2C first",
    "write_return_meaning": "bytes accepted",
    "input_visibility": "after sync",
    "request_accepted": "notify",
    "dma_completion": "driver IRQ",
    "attention_completion": "status DONE",
    "stale_done_clear": "seq match",
    "readback_consume": "after read",
    "timeout_handling": "finite monotonic",
    "short_io_handling": "fault",
    "error_recovery": "explicit reset",
    "clock_method": "time.monotonic",
    "poll_interval": "1ms",
    "correctness_method": "byte compare",
}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _write(self, data):
        p = self.dir / "binding.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_missing_binding_file_fails_closed(self):
        rc = runner.main(["--binding", str(self.dir / "nope.json"),
                          "--device", "pcie_transport.tests.mock_device"])
        self.assertEqual(rc, 1)

    def test_incomplete_binding_fails_closed(self):
        inc = dict(REAL_FIELDS)
        inc["h2c_node"] = ""
        rc = runner.main(["--binding", str(self._write(inc)),
                          "--device", "pcie_transport.tests.mock_device"])
        self.assertEqual(rc, 1)

    def test_mock_kind_binding_refused(self):
        mock = dict(REAL_FIELDS)
        mock["kind"] = "mock"
        rc = runner.main(["--binding", str(self._write(mock)),
                          "--device", "pcie_transport.tests.mock_device"])
        self.assertEqual(rc, 1)

    def test_bad_device_module_fails_closed(self):
        rc = runner.main(["--binding", str(self._write(REAL_FIELDS)),
                          "--device", "pcie_transport.no_such_module"])
        self.assertEqual(rc, 1)

    def test_check_mode_validates_without_running(self):
        rc = runner.main(["--binding", str(self._write(REAL_FIELDS)),
                          "--device", "pcie_transport.tests.mock_device", "--check"])
        self.assertEqual(rc, 0)

    def test_short_rounds_rejected(self):
        rc = runner.main(["--binding", str(self._write(REAL_FIELDS)),
                          "--device", "pcie_transport.tests.mock_device", "--rounds", "3"])
        self.assertEqual(rc, 2)

    def test_full_30_round_run_writes_evidence(self):
        out = self.dir / "evidence"
        rc = runner.main(["--binding", str(self._write(REAL_FIELDS)),
                          "--device", "pcie_transport.tests.mock_device",
                          "--rounds", "30", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertTrue((out / "op_test_summary.json").is_file())
        self.assertTrue((out / "op_test_rounds.csv").is_file())
        summary = json.loads((out / "op_test_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["backend"], "board")
        self.assertEqual(summary["rounds"], 30)
        self.assertEqual(summary["errors"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
