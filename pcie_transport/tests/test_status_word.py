"""PC-only tests for the application status-word decoder (no device access)."""
import unittest

from pcie_transport import status_word as sw


class StatusWordTests(unittest.TestCase):
    def test_decode_bits(self):
        s = sw.decode(0x00000001)
        self.assertTrue(s.done)
        self.assertEqual(s.err, sw.ERR_OK)
        self.assertTrue(s.ok)

    def test_err_codes(self):
        for code, name in ((sw.ERR_SEQ, "SEQ_ERR"), (sw.ERR_LAYER, "LAYER_ERR"), (sw.ERR_CRC, "CRC_ERR")):
            s = sw.decode(code << 1)
            self.assertEqual(s.err, code)
            self.assertEqual(s.err_name, name)
            self.assertFalse(s.ok)

    def test_reserved(self):
        s = sw.decode(0xABC00010)
        self.assertEqual(s.reserved, 0x0ABC0001)
        self.assertEqual(s.err, sw.ERR_OK)

    def test_unknown_err_is_reserved(self):
        s = sw.decode((0x7 << 1))
        self.assertEqual(s.err_name, "RESERVED")

    def test_rejects_out_of_range(self):
        for bad in (-1, 0x1_0000_0000, 1.5, "1", None):
            with self.assertRaises(ValueError):
                sw.decode(bad)

    def test_describe(self):
        self.assertIn("DONE=1", sw.decode(0x1).describe())


if __name__ == "__main__":
    unittest.main()
