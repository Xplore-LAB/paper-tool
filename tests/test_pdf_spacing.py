import tempfile,unittest
from pathlib import Path
try:
    from reportlab.pdfgen import canvas
except ImportError:
    canvas = None
import paper_to_zotero as m

@unittest.skipIf(canvas is None, "reportlab is optional for PDF fixtures")
class PdfSpacingTests(unittest.TestCase):
    def test_collapsed_spaces_need_exact_title_author_and_doi(self):
        paper=m.paper_from_crossref(m.SAMPLE_RECORD)
        with tempfile.TemporaryDirectory() as d:
            for correct in [True,False]:
                p=Path(d)/f'{correct}.pdf';c=canvas.Canvas(str(p))
                c.drawString(20,750,paper['title'].replace(' ',''))
                c.drawString(20,730,paper['doi'] if correct else '10.9999/unrelated')
                c.drawString(20,710,paper['authors'][0]['first']+paper['authors'][0]['last'])
                c.save();self.assertEqual(m.verify_pdf(p,paper)[0],correct)
