"""Tests for the bilingual interface: every tr() key has a German translation."""
import ast
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cableiq as c  # noqa: E402
import cableiq_i18n as i18n  # noqa: E402

FIELD = re.compile(r"\{(\w*)\}")
# dynamically generated keys (Record.result, autotest names, reasons)
DYNAMIC = (list(c.RESULT_TEXT.values()) + [n for s in c.SPEC_SETS.values() for n in s]
           + ["Wiremap", "Length (termination error)", "Impedance error", "none"])


def used_keys():
    keys = set()
    for f in ROOT.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys.add(n.args[0].value)
    return keys


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("en")

    def test_every_key_has_translation(self):
        missing = sorted(k for k in used_keys() | set(DYNAMIC) if k not in i18n.DE)
        self.assertEqual(missing, [])

    def test_no_superfluous_entries(self):
        extra = sorted(k for k in i18n.DE if k not in used_keys() | set(DYNAMIC))
        self.assertEqual(extra, [])

    def test_placeholders_match(self):
        for k, v in i18n.DE.items():
            with self.subTest(k):
                self.assertEqual(sorted(FIELD.findall(k)), sorted(FIELD.findall(v)))

    def test_switching(self):
        i18n.set_lang("de")
        self.assertEqual(i18n.tr("Qualified"), "Qualifiziert")
        self.assertEqual(i18n.nf(15.94, 1), "15,9")
        i18n.set_lang("en")
        self.assertEqual(i18n.tr("Qualified"), "Qualified")
        self.assertEqual(i18n.nf(15.94, 1), "15.9")
        self.assertEqual(i18n.set_lang("fr"), "en")  # unknown -> English

    def test_formats(self):
        import datetime
        d = datetime.datetime(2026, 10, 16, 18, 12, 13)
        i18n.set_lang("de")
        self.assertEqual(i18n.dt(d), "16.10.2026 18:12:13")
        i18n.set_lang("en")
        self.assertEqual(i18n.dt(d, False), "2026-10-16 18:12")


if __name__ == "__main__":
    unittest.main()
