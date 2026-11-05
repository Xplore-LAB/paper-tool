"""Offline tests: never contact Crossref, OpenAlex, or an actual Zotero library."""

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_to_zotero as m


class FakeZotero:
    def __init__(self):
        self.saved = []
        self.attachments = []

    def collections(self):
        return [
            {"key": "AAAA2345", "name": "工业时序预测", "path": "工业人工智能/工业时序预测"},
            {"key": "BBBB2345", "name": "控制性能评价", "path": "工业人工智能/控制性能评价"},
        ]

    def collection_items(self, key):
        if key == "AAAA2345":
            return [{"title": "Long-term oxygen demand prediction based on diffusion model integrating production plans"}]
        return [{"title": "Process control performance assessment in chemical plants"}]

    def items(self):
        return []

    def ensure_item(self, paper, key):
        self.saved.append((paper["doi"], key))
        return "PAPER234", True

    def has_pdf(self, key):
        return False

    def upload_pdf(self, parent, path):
        self.attachments.append((parent, path))
        return "ATTACH23"


class PaperWorkflowTest(unittest.TestCase):
    def test_doi_and_metadata(self):
        self.assertEqual(m.doi_from("DOI: https://doi.org/10.1016/j.ins.2026.123800."), "10.1016/j.ins.2026.123800")
        paper = m.paper_from_crossref(m.SAMPLE_RECORD)
        self.assertEqual(paper["journal"], "Information Sciences")
        self.assertEqual(paper["pages"], "123800")
        self.assertEqual(paper["year"], "2026")

    def test_reference_without_doi_matches_accurately(self):
        self.assertIsNone(m.doi_from(m.SAMPLE_REF))
        with patch.object(m, "get_json", return_value={"message": {"items": [m.SAMPLE_RECORD]}}):
            record, score = m.crossref_metadata(m.SAMPLE_REF)
        self.assertEqual(record["DOI"], "10.1016/j.ins.2026.123800")
        self.assertGreaterEqual(score, 0.98)

    def test_ambiguous_reference_is_not_silently_matched(self):
        with patch.object(m, "get_json", return_value={"message": {"items": [m.SAMPLE_RECORD]}}):
            with self.assertRaises(m.PaperError):
                m.crossref_metadata("Unrelated title, 2023")

    def test_collection_auto_suggest_uses_existing_items(self):
        paper = m.paper_from_crossref(m.SAMPLE_RECORD)
        selected, ranked = m.choose_collection(FakeZotero(), paper, None)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["key"], "AAAA2345")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_collection_exact_path(self):
        paper = m.paper_from_crossref(m.SAMPLE_RECORD)
        selected, _ = m.choose_collection(FakeZotero(), paper, "工业人工智能/控制性能评价")
        self.assertEqual(selected["key"], "BBBB2345")

    def test_offline_preview_does_not_write_zotero(self):
        z = FakeZotero()
        args = argparse.Namespace(demo=True, apply=False, collection="工业人工智能/工业时序预测", out="unused")
        result = m.process(m.SAMPLE_REF, args, z)
        self.assertEqual(result["status"], "PREVIEW")
        self.assertEqual(result["zotero"], "not_modified")
        self.assertEqual(z.saved, [])

    def test_apply_with_no_pdf_still_saves_metadata(self):
        z = FakeZotero()
        args = argparse.Namespace(demo=False, apply=True, collection="工业人工智能/工业时序预测", out="unused")
        with patch.object(m, "crossref_metadata", return_value=(m.SAMPLE_RECORD, 1.0)), \
             patch.object(m, "pdf_candidates", return_value=[]), \
             tempfile.TemporaryDirectory() as d:
            args.out = d
            result = m.process(m.SAMPLE_REF, args, z)
        self.assertEqual(result["status"], "PDF_PENDING")
        self.assertEqual(result["zotero"], "created")
        self.assertEqual(z.saved, [("10.1016/j.ins.2026.123800", "AAAA2345")])
        self.assertEqual(z.attachments, [])

    def test_pdf_upload_local_api_three_phase(self):
        z = m.ZoteroLocal.__new__(m.ZoteroLocal)
        z.key = "fake"
        z.server_id = "fake-server"
        z.base = m.BASE
        z.write_item = lambda entry: "ATTACH23"
        calls = []
        def fake_call(method, endpoint, data=None, *, headers=None):
            calls.append((method, endpoint, data, headers))
            if endpoint.endswith("/file") and "If-None-Match" in (headers or {}) and b"md5=" in data:
                return ({"url": "http://127.0.0.1:23119/api/local/uploads/123", "uploadKey": "123", "contentType": "application/octet-stream", "prefix": "", "suffix": ""}, {})
            return ({}, {})
        z.call = fake_call
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "demo.pdf"
            f.write_bytes(b"%PDF-1.5\n%%EOF\n")
            with patch.object(m, "request_bytes", return_value=(201, {}, b"", "http://127.0.0.1:23119/api/local/uploads/123")) as remote:
                key = z.upload_pdf("PAPER234", f)
        self.assertEqual(key, "ATTACH23")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][2], b"upload=123")
        self.assertTrue(remote.called)

    def test_download_url_is_safe(self):
        self.assertTrue(m.safe_pdf_url("https://repository.example.edu/file.pdf"))
        self.assertFalse(m.safe_pdf_url("http://repository.example.edu/file.pdf"))
        self.assertFalse(m.safe_pdf_url("https://127.0.0.1/secret.pdf"))

    def test_pdf_identity_check(self):
        try:
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab is optional for this test")
        paper = m.paper_from_crossref(m.SAMPLE_RECORD)
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "test.pdf"
            c = canvas.Canvas(str(dest))
            c.drawString(30, 750, paper["title"])
            c.drawString(30, 735, "DOI: " + paper["doi"])
            c.save()
            valid, reason = m.verify_pdf(dest, paper)
            self.assertTrue(valid, reason)
            dest.write_text("This is an HTML login page", encoding="utf-8")
            valid, _ = m.verify_pdf(dest, paper)
            self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
