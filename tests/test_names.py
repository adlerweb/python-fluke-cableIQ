"""Tests for naming autotests from the block identifier masks (no sample data needed)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import cableiq as c  # noqa: E402


def record_with_blocks(ids):
    raw = bytearray(c.REC_LEN)
    for k, ident in enumerate(ids):
        raw[c.TESTS_AT + c.TEST_LEN * k] = ident
    return c.Record(bytes(raw))


class AutotestNamesTest(unittest.TestCase):
    def test_known_sets_are_kept(self):
        self.assertEqual(c.autotest_names([0x1F, 0x13, 0x13, 0x1F]), c.SPEC_SETS[4])
        self.assertEqual(c.autotest_names([0x0F, 0x03, 0x03, 0x03, 0x0F, 0x06]), c.SPEC_SETS[6])
        self.assertEqual(c.autotest_names([0x1F, 0x13, 0x13, 0x13, 0x1F, 0x09, 0x06]), c.SPEC_SETS[7])

    def test_unique_guess_for_unknown_sets(self):
        self.assertEqual(c.autotest_names([0x09, 0x06]), ["1394b S100", "Telco"])
        self.assertEqual(c.autotest_names([0x06]), ["Telco"])

    def test_ambiguous_masks_stay_generic(self):
        self.assertEqual(c.autotest_names([0x0F, 0x09]), ["Autotest 1", "Autotest 2"])
        self.assertEqual(c.autotest_names([0x03, 0x03]), ["Autotest 1", "Autotest 2"])

    def test_record_uses_names(self):
        self.assertEqual([t["name"] for t in record_with_blocks([0x09, 0x06]).autotests], ["1394b S100", "Telco"])

    def test_impossible_masks(self):
        self.assertEqual(c.autotest_names([0x06, 0x09]), ["Autotest 1", "Autotest 2"])  # wrong order
        self.assertEqual(c.autotest_names([0x05]), ["Autotest 1"])


if __name__ == "__main__":
    unittest.main()
