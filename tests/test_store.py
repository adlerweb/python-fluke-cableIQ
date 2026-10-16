"""Tests for saving and loading measurement sets."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cableiq as c  # noqa: E402
import cableiq_store as st  # noqa: E402


def records():
    _, recs = c.read_all(c.ReplayTransport(str(ROOT / "samples" / "import.pcap")))
    for p in sorted((ROOT / "samples" / "records").glob("*.bin")):
        recs.append(c.Record(p.read_bytes()))
    return recs


HAVE_SAMPLES = (ROOT / "samples" / "import.pcap").exists() and (ROOT / "samples" / "records").is_dir()


@unittest.skipUnless(HAVE_SAMPLES, "samples/ is missing (local only, not in the repository)")
class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "satz.json"
        self.recs = records()

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_all_data(self):
        ops = [None] * len(self.recs)
        ops[0] = ["Company", "Team"]
        logo = pathlib.Path(self.tmp.name) / "logo.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\n-testdaten-")
        st.save_set(self.path, "1234567", self.recs, ops, {"location": "Server room", "tester": "Jane Doe"},
                    str(logo))
        s = st.load_set(self.path)
        self.assertEqual(s["serial"], "1234567")
        self.assertEqual([r.raw for r in s["recs"]], [r.raw for r in self.recs])  # byte-identical
        self.assertEqual([r.name for r in s["recs"]], [r.name for r in self.recs])
        self.assertEqual(s["ops"][0], ["Company", "Team"])
        self.assertTrue(all(o is None for o in s["ops"][1:]))
        self.assertEqual(s["protocol"], {"location": "Server room", "tester": "Jane Doe"})
        self.assertEqual(s["logo"], ("logo.png", logo.read_bytes()))
        # derived values stay the same after loading
        self.assertEqual(s["recs"][5].qualified_names, self.recs[5].qualified_names)

    def test_notes(self):
        notes = [None] * len(self.recs)
        notes[1] = "Cable re-terminated\nsecond line"
        st.save_set(self.path, "1", self.recs, None, None, "", notes)
        s = st.load_set(self.path)
        self.assertEqual(s["notes"][1], notes[1])
        self.assertTrue(all(n == "" for i, n in enumerate(s["notes"]) if i != 1))

    def test_without_report_details(self):
        st.save_set(self.path, "1", self.recs[:2])
        s = st.load_set(self.path)
        self.assertEqual((len(s["recs"]), s["protocol"], s["logo"]), (2, {}, None))

    def test_error_cases(self):
        self.path.write_text("not json")
        with self.assertRaises(st.StoreError):
            st.load_set(self.path)
        self.path.write_text(json.dumps({"format": "other"}))
        with self.assertRaises(st.StoreError):
            st.load_set(self.path)
        st.save_set(self.path, "1", self.recs[:1])
        d = json.loads(self.path.read_text())
        d["records"][0]["raw"] = d["records"][0]["raw"][:20]
        self.path.write_text(json.dumps(d))
        with self.assertRaises(st.StoreError):
            st.load_set(self.path)
        d["version"] = 99
        self.path.write_text(json.dumps(d))
        with self.assertRaises(st.StoreError):
            st.load_set(self.path)
        with self.assertRaises(st.StoreError):
            st.load_set(pathlib.Path(self.tmp.name) / "missing.json")


if __name__ == "__main__":
    unittest.main()
