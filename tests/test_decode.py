"""Regression test: result, qualification and reasons against reference values (list and detail view)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cableiq as c  # noqa: E402

ALL6 = ["1000BASE-T", "100BASE-TX", "10BASE-T", "Voice over IP", "Wiremap only", "Telco"]
Q4 = ["1000BASE-T", "100BASE-TX", "Voice over IP", "Wiremap only"]
# name -> (result, qualified autotests); source: reference values of 2026-10-16
TRUTH = {
    "Gebäude B10 8.8": ("Qualified", Q4), "Gebäude B10 8.7": ("Qualified", Q4),
    "Gebäude B35c9 B02": ("Qualified", Q4), "Gebäude Büro B01": ("Qualified", Q4),
    "Gebäude Büro 2": ("Qualified", Q4),
    "Gebäude Büro 1": ("Disqualified", ["10BASE-T", "Wiremap only", "Telco"]),
    "Building Officea 9": ("Qualified", ALL6), "Building Officea 8": ("Qualified", ALL6),
    "Building Officea 7": ("Disqualified", ["Telco"]),
    "Building Officea 6": ("Disqualified", ["100BASE-TX", "10BASE-T", "Voice over IP", "Telco"]),
    "Building Officea 5": ("Qualified", ALL6), "Building Officea 4": ("Disqualified", []),
    "Building Officea 3": ("Disqualified", ["Telco"]),
    "Building Officea 2": ("Qualified", ALL6), "Building Officea 1": ("Qualified", ALL6),
    "Los AA": ("Information", []), "Los AAA": ("Disqualified", []), "Los 1": ("Disqualified", []),
    "Los 2": ("Disqualified", ["100BASE-TX", "Voice over IP"]), "Los 3": ("Disqualified", []),
    "Los 4": ("Disqualified", []), "Los 5": ("Disqualified", []),
}


def load():
    _, recs = c.read_all(c.ReplayTransport(str(ROOT / "samples" / "import.pcap")))
    for p in sorted((ROOT / "samples" / "records").glob("*.bin")):
        recs.append(c.Record(p.read_bytes()))
    return {r.name.strip(" #"): r for r in recs}


HAVE_SAMPLES = (ROOT / "samples" / "import.pcap").exists() and (ROOT / "samples" / "records").is_dir()


@unittest.skipUnless(HAVE_SAMPLES, "samples/ is missing (local only, not in the repository)")
class DecodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = load()

    def test_alle_bekannten_messungen_vorhanden(self):
        self.assertEqual(sorted(self.recs), sorted(TRUTH))

    def test_ergebnis_und_qualifizierung(self):
        for name, (res, qual) in TRUTH.items():
            with self.subTest(name):
                self.assertEqual(self.recs[name].result, res)
                self.assertEqual(self.recs[name].qualified_names, qual)

    def test_detailansicht_buero1(self):
        t = {a["name"]: a for a in self.recs["Gebäude Büro 1"].autotests}
        self.assertEqual(len(t), 7)
        for n in ("1000BASE-T", "100BASE-TX", "Voice over IP", "1394b S100"):
            self.assertFalse(t[n]["qualified"])
            self.assertEqual(t[n]["reason"], "Impedance error")
        for n in ("10BASE-T", "Wiremap only", "Telco"):
            self.assertTrue(t[n]["qualified"])

    def test_fault_mask_of_the_test_cables(self):
        """Word 0x204 (bit 0-7 = wire 1-8, bit 8 = shield) matches the deliberately built faults."""
        expected = {"Los AA": 0, "Los AAA": 0x104, "Los 1": 0x44, "Los 2": 0x58, "Los 3": 0x4C,
                    "Los 4": 0x5C, "Los 5": 0x15C, "Building Officea 7": 0x102, "Building Officea 6": 0x180,
                    "Building Officea 4": 0x180, "Building Officea 3": 0x002, "Gebäude B10 8.8": 0}
        for name, mask in expected.items():
            with self.subTest(name):
                r = self.recs[name]
                self.assertEqual(int.from_bytes(r.raw[0x204:0x206], "little"), mask)
                self.assertEqual(sum(1 << i for i, w in enumerate(r.wires) if w["fault"]), mask)

    def test_wiremap_of_the_test_cables(self):
        w = {x["name"]: x for x in self.recs["Los 2"].wires}
        self.assertEqual((w["4"]["far"], w["5"]["far"], w["7"]["state"]), (["5"], ["4"], "open"))
        w = {x["name"]: x for x in self.recs["Los 4"].wires}
        self.assertEqual((w["3"]["far"], w["3"]["shorts"], w["4"]["far"]), (["3", "4"], ["5"], ["5"]))
        self.assertTrue(self.recs["Los AA"].wiremap_ok)  # no far end: no wiremap error
        self.assertTrue(self.recs["Los AA"].no_remote)
        self.assertFalse(self.recs["Los 5"].shield_ok)

    def test_reasons_wording(self):
        """Reasons according to the reference values (Los 1 and Los 5, detail view of 2026-10-16)."""
        expected = {"1000BASE-T": "Wiremap; Length (termination error)", "100BASE-TX": "Wiremap",
                    "Voice over IP": "Wiremap", "Wiremap only": "Wiremap; Length (termination error)"}
        for name in ("Los 1", "Los 5"):
            with self.subTest(name):
                t = {a["name"]: a["reason"] for a in self.recs[name].autotests}
                self.assertEqual(t, expected)
                self.assertTrue(all(not a["qualified"] for a in self.recs[name].autotests))

    def test_tested_by(self):
        self.assertEqual(self.recs["Los 1"].operator_fields, ["Example Corp", "IT Infrastructure"])
        self.assertEqual(self.recs["Gebäude B10 8.8"].operator_fields, [])  # placeholder "="
        self.assertEqual(self.recs["Gebäude B10 8.8"].operator_lines, ["", ""])
        self.assertEqual(self.recs["Los 1"].operator_lines[1], "IT Infrastructure")

    def test_length_according_to_device(self):
        self.assertAlmostEqual(self.recs["Gebäude Büro 1"].device_length[0], 27.7, 1)
        self.assertTrue(self.recs["Building Officea 7"].device_length[1])  # "~1.8"


if __name__ == "__main__":
    unittest.main()
