import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cableiq
from PySide6.QtWidgets import QApplication

import cableiq_pdf

PCAP = pathlib.Path(__file__).resolve().parent.parent / "samples" / "import.pcap"


@unittest.skipUnless(PCAP.exists(), "samples/import.pcap is missing")
class PdfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.serial, cls.recs = cableiq.read_all(cableiq.ReplayTransport(str(PCAP)))

    def export(self, recs, **kw):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.pdf")
            cableiq_pdf.export_pdf(path, recs, self.serial, "Ort", "Person", "", **kw)
            return pathlib.Path(path).read_bytes()

    def test_einzelne_messung_eine_seite(self):
        data = self.export(self.recs[:1], notes=["Notiz"], signature=True)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page\n"), 1)

    def test_uebersicht_plus_eine_seite_je_messung(self):
        data = self.export(self.recs[:3], signature=True)
        self.assertEqual(data.count(b"/Type /Page\n"), 4)


if __name__ == "__main__":
    unittest.main()
