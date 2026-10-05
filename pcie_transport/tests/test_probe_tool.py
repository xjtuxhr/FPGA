"""PC-side guard tests for the read-only enumeration probe (no board access).

The probe is a shell script that runs on the RK3576 during the bring-up
window. These tests run anywhere (no bash needed): they read the script text
and enforce that it stays read-only, so a later edit cannot silently turn it
into a mutating/rebind/flash script.
"""
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "probe_enumeration.sh"

# Tokens that would change board state. They may appear in comments (the
# script documents what it must NOT do); the scan below ignores comment lines.
FORBIDDEN_CODE = [
    r"\bmodprobe\b",
    r"\binsmod\b",
    r"\brmmod\b",
    r"\brebind\b",
    r"\brescan\b",
    r"\bdevmem\b",
    r"\bsetpci\b",
    r"\bdd\b",
    r"mmcblk",
    r"\bmount\b",
    r"\bumount\b",
    r"\bflash_erase\b",
    r"\bfw_setenv\b",
    r"\bsgdisk\b",
    r"\bsudo\b",
]


def code_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


class ProbeToolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT}")
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_declares_read_only_intent(self):
        self.assertIn("READ-ONLY", self.text)

    def test_has_no_mutating_commands_in_code(self):
        code = code_lines(self.text)
        for pattern in FORBIDDEN_CODE:
            self.assertIsNone(
                re.search(pattern, code),
                f"read-only probe contains mutating token {pattern!r}",
            )

    def test_no_redirection_into_system_paths(self):
        code = code_lines(self.text).replace(">/dev/null", "")
        self.assertNotIn(">/dev/", code)

    def test_emits_structured_sections_and_result(self):
        self.assertIn("section", self.text)
        self.assertIn("NO_PCI_ENDPOINT", self.text)
        self.assertIn("PCI_ENUMERATED", self.text)
        self.assertIn("probe_enumeration complete", self.text)

    def test_probe_does_not_require_root(self):
        # The probe is meant to run as the ordinary kvdev user.
        self.assertIsNone(re.search(r"\bsudo\b", code_lines(self.text)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
