import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_tool
import paper_tool as t


class RegressionTests(unittest.TestCase):
    def test_cached_zotero_metadata_can_fall_back_after_oa_failure(self):
        with tempfile.TemporaryDirectory() as out:
            args = test_tool.ToolTests().args(out)
            paper = t.core.paper_from_crossref(t.core.SAMPLE_RECORD)
            args.doi_index = {paper['doi']: {'DOI': paper['doi']}}
            record = dict(t.core.SAMPLE_RECORD, link=[{'URL': 'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
            with patch.object(t.core, 'paper_from_zotero', return_value=paper), patch.object(t.core, 'crossref_metadata', return_value=(record, 1)) as lookup, patch.object(t.core, 'pdf_candidates', return_value=[]), patch.object(t.core, 'download_verified', return_value=(None, None, [])), patch.object(t.subprocess, 'run', return_value=type('Result', (), {'returncode': 1})()) as browser:
                result = t.run_reference(paper['doi'], args)
                self.assertEqual(result['status'], 'PDF_PENDING')
                lookup.assert_called_once_with(paper['doi'])
                self.assertIn('S0020025526007310', browser.call_args.args[0])
                self.assertTrue(Path(browser.call_args.args[0][1]).is_file())

    def test_cached_metadata_only_keeps_zero_external_lookups(self):
        with tempfile.TemporaryDirectory() as out:
            args = test_tool.ToolTests().args(out)
            args.metadata_only = True
            paper = t.core.paper_from_crossref(t.core.SAMPLE_RECORD)
            args.doi_index = {paper['doi']: {}}
            with patch.object(t.core, 'paper_from_zotero', return_value=paper), patch.object(t.core, 'crossref_metadata') as lookup, patch.object(t.core, 'pdf_candidates') as candidates:
                t.run_reference(paper['doi'], args)
                lookup.assert_not_called()
                candidates.assert_not_called()

    def test_release_excludes_machine_state(self):
        import zipfile
        from build_release import build_release
        with tempfile.TemporaryDirectory() as out:
            archive = build_release(Path(out) / 'release.zip')
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                self.assertIn('paper-tool/paper_tool_assets/browser_pdf.mjs', names)
                self.assertIn('paper-tool/LICENSE', names)
                self.assertIn('paper-tool/MANIFEST.in', names)
                self.assertFalse(any('/.local/' in name for name in names))
                self.assertFalse(any('/.git/' in name or '/.local-auth/' in name or name.endswith(('.dpapi', '/.env', '.pdf')) for name in names))

    def test_version_cli_matches_package_metadata(self):
        import contextlib
        import io
        import re
        metadata = (t.ROOT / 'pyproject.toml').read_text()
        declared = re.search(r'^version = "([^"]+)"', metadata, re.M).group(1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit:
            t.main(['--version'])
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), 'paper-tool '+declared)

    def test_doctor_checks_the_configured_proxy_and_zotero_ports(self):
        from unittest.mock import MagicMock
        with patch.object(t.socket, 'create_connection', return_value=MagicMock()) as connect:
            result = t.doctor('http://127.0.0.1:9081', zotero_base='http://127.0.0.1:33129/api')
        self.assertTrue(result['ok'])
        ports = {call.args[0][1] for call in connect.call_args_list}
        self.assertEqual(ports, {9081, 18806, 33129})
