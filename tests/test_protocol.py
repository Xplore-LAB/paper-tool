"""Loopback HTTP protocol tests; this server is a test double, not Zotero."""
import hashlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from paper_tool import core as m


class TransportTest(unittest.TestCase):
    @patch('paper_tool.auth.save')
    @patch('paper_tool.auth.load', return_value='')
    def test_authorization_item_upload_and_repeat_over_http(self, _load, _save):
        state = {"items": [], "uploaded": b"", "registered": False, "authorizations": 0,
                 'fail_upload_once': True}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, data=None):
                body = json.dumps(data).encode() if data is not None else b""
                self.send_response(status)
                self.send_header("Zotero-Server-ID", "test-instance")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/api/":
                    return self.reply(200, {})
                if path.endswith("/collections"):
                    return self.reply(200, [{"data": {"key": "TESTCOL1", "name": "Test", "parentCollection": False}}])
                if path.endswith("/children"):
                    return self.reply(200, [{"data": x} for x in state["items"] if x.get("parentItem") == "ITEM0001"])
                if path.endswith('/file/view/url'):
                    if not state['registered']:
                        return self.reply(404, {})
                    body = b'file:///another-computer/zotero/storage/ATTACH01/fixture.pdf'
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
                if path.endswith("/items"):
                    return self.reply(200, [{"data": x} for x in state["items"] if x["itemType"] != "attachment"])
                return self.reply(404, {})

            def do_POST(self):
                path = urlparse(self.path).path
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if path.startswith("/api/local/uploads/"):
                    if state['fail_upload_once']:
                        state['fail_upload_once'] = False
                        return self.reply(503, {'error': 'simulated interruption'})
                    if hashlib.md5(body).hexdigest() != state["md5"]:
                        return self.reply(400, {})
                    state["uploaded"] = body
                    return self.reply(201)
                if self.headers.get("Zotero-Server-ID") != "test-instance":
                    return self.reply(428, {})
                if path == "/api/local/authorize":
                    state["authorizations"] += 1
                    return self.reply(200, {"key": "test-only-key", "remember": True})
                if self.headers.get("Zotero-API-Key") != "test-only-key":
                    return self.reply(401, {})
                if path.endswith("/items"):
                    if self.headers.get("Content-Type") != "application/json":
                        return self.reply(400, {"error": "missing JSON type after authorization"})
                    item = json.loads(body)[0]
                    item.update(key="ITEM0001" if not item.get("parentItem") else "ATTACH01", version=1)
                    state["items"].append(item)
                    return self.reply(200, {"successful": {"0": {"data": item}}})
                if path.endswith("/file"):
                    form = parse_qs(body.decode())
                    if "md5" in form:
                        if state['registered'] and state['md5'] == form['md5'][0]:
                            return self.reply(200, {'exists': 1})
                        state["md5"] = form["md5"][0]
                        # Zotero returns its own port, different from an SSH forwarding endpoint.
                        return self.reply(200, {"url": "http://127.0.0.1:23119/api/local/uploads/test-upload",
                                                "uploadKey": "test-upload", "prefix": "", "suffix": "",
                                                "contentType": "application/octet-stream"})
                    if form.get("upload") == ["test-upload"] and state["uploaded"]:
                        state["registered"] = True
                        state['items'][-1]['md5'] = state['md5']
                        return self.reply(204)
                return self.reply(404, {})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            z = m.ZoteroLocal(f"http://127.0.0.1:{server.server_port}/api")
            z.key = ""
            self.assertEqual(z.collections()[0]["path"], "Test")
            paper = m.paper_from_crossref(m.SAMPLE_RECORD)
            key, created = z.ensure_item(paper, "TESTCOL1")
            self.assertTrue(created)
            payload = b"%PDF-1.5\ntransport-test\n%%EOF\n"
            with tempfile.TemporaryDirectory() as temp:
                pdf = Path(temp) / "fixture.pdf"
                pdf.write_bytes(payload)
                with self.assertRaises(m.PaperError):
                    z.upload_pdf(key, pdf)
                self.assertEqual(len(state['items']), 2)
                repaired = z.ensure_pdf(key, pdf, paper)
                self.assertEqual(repaired, {'status': 'PDF_ATTACHED', 'attachment_key': 'ATTACH01'})
                repeated = z.ensure_pdf(key, pdf, paper)
                self.assertEqual(repeated['status'], 'PDF_ALREADY_PRESENT')
                self.assertEqual(len(state['items']), 2)
            self.assertEqual(state["uploaded"], payload)
            self.assertTrue(state["registered"])
            self.assertEqual(state["authorizations"], 1)
            self.assertTrue(z.has_pdf(key))
            key2, created2 = z.ensure_item(paper, "TESTCOL1")
            self.assertEqual(key, key2)
            self.assertFalse(created2)
            self.assertEqual(len(state["items"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_pagination_reads_beyond_first_hundred(self):
        z = m.ZoteroLocal.__new__(m.ZoteroLocal)
        with patch.object(z, "call", side_effect=[([{}] * 100, {}), ([{}], {})]) as call:
            self.assertEqual(len(z.all_pages("/users/0/items?itemType=-attachment")), 101)
            self.assertIn("start=100", call.call_args.args[1])

    def test_cited_doi_alone_does_not_verify_wrong_paper(self):
        try:
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab is optional for this test")
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "wrong.pdf"
            c = canvas.Canvas(str(p))
            c.drawString(20, 700, "A completely unrelated paper")
            c.drawString(20, 680, "Reference DOI: " + m.SAMPLE_RECORD["DOI"])
            c.save()
            self.assertFalse(m.verify_pdf(p, m.paper_from_crossref(m.SAMPLE_RECORD))[0])

    def test_journal_disambiguates_same_title_and_author(self):
        original = m.SAMPLE_RECORD
        other = dict(original, DOI="10.9999/other", **{"container-title": ["Another journal"]})
        with patch.object(m, "get_json", return_value={"message": {"items": [other, original]}}):
            record, score = m.crossref_metadata(m.SAMPLE_REF)
        self.assertEqual(record["DOI"], original["DOI"])

    def test_institutional_pdf_link_comes_from_crossref_pii(self):
        import argparse
        record = dict(m.SAMPLE_RECORD, link=[{"URL": "https://api.elsevier.com/content/article/PII:S0020025526007310?httpAccept=text/xml", "content-type": "text/xml"}])
        args = argparse.Namespace(demo=False, apply=False, institutional=True)
        with patch.object(m, "crossref_metadata", return_value=(record, 1.0)), \
             patch.object(m, "pdf_candidates", return_value=[]):
            result = m.process(m.SAMPLE_REF, args)
        self.assertEqual(result["pdf_candidates"][0]["source"], "institutional_publisher")
        self.assertIn("S0020025526007310/pdfft", result["pdf_candidates"][0]["url"])

    def test_zotero_endpoint_cannot_be_public(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error:
                m.main(["--demo", "--no-zotero", "--zotero-base", "http://192.0.2.1:23119/api"])
        self.assertEqual(error.exception.code, 2)

    def test_pdf_download_rate_and_attempt_spacing(self):
        for rate in (128, 0):
            with self.subTest(rate_kib=rate):
                self.check_pdf_download_policy(rate)

    def check_pdf_download_policy(self, rate):
        clock = [0.0]
        payload = b"%PDF-1.5\n" + b"x" * (256 * 1024)
        class Response(io.BytesIO):
            def geturl(self):
                return "https://repository.example.edu/paper.pdf"
        class Opener:
            def open(self, *args, **kwargs):
                return Response(payload)
        def advance(seconds):
            clock[0] += seconds
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(m, "PDF_RATE_KIB", rate), \
             patch.object(m, "PDF_INTERVAL", 30), \
             patch.object(m, "LAST_PDF_ATTEMPT", None), \
             patch.object(m, "build_opener", return_value=Opener()), \
             patch.object(m, "verify_pdf", return_value=(True, "test fixture")), \
             patch.object(m.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(m.time, "sleep", side_effect=advance):
            candidates = [{"url": "https://repository.example.edu/paper.pdf", "source": "test"}]
            first, _, _ = m.download_verified({"doi": "10.9999/first"}, candidates, Path(temp))
            self.assertEqual(first.read_bytes(), payload)
            first_end = clock[0]
            duration = len(payload) / (rate * 1024) if rate else 0
            self.assertGreaterEqual(first_end, duration)
            second, _, _ = m.download_verified({"doi": "10.9999/second"}, candidates, Path(temp))
            self.assertEqual(second.read_bytes(), payload)
            self.assertGreaterEqual(clock[0] - first_end, 30 + duration)


if __name__ == "__main__":
    unittest.main()
