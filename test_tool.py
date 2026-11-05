import argparse
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import paper_tool as t


class ToolTests(unittest.TestCase):
    def args(self, out):
        return argparse.Namespace(command='fetch',out=out,oa_only=False,zotero=False,proxy='http://127.0.0.1:1081',cdp='http://127.0.0.1:18806')

    def test_preview_never_downloads(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.command='preview'
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified') as download:
                self.assertEqual(t.run_reference('test',args)['status'],'PREVIEW')
                download.assert_not_called()

    def test_browser_fallback_validates_before_acceptance(self):
        record=dict(t.core.SAMPLE_RECORD,link=[{'URL':'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
        for verified in (True,False):
            with self.subTest(verified=verified),tempfile.TemporaryDirectory() as out:
                def browser(cmd,**kwargs):
                    Path(cmd[cmd.index('--out')+1]).write_bytes(b'%PDF-test')
                    return argparse.Namespace(returncode=0)
                with patch.object(t.core,'crossref_metadata',return_value=(record,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(None,None,[])),patch.object(t.subprocess,'run',side_effect=browser),patch.object(t.core,'verify_pdf',return_value=(verified,'fixture')):
                    r=t.run_reference('test',self.args(out))
                    self.assertEqual(r['status'],'PDF_SAVED' if verified else 'PDF_PENDING')

    def test_oa_only_never_opens_institutional_browser(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.oa_only=True
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(None,None,[])),patch.object(t.subprocess,'run') as browser:
                self.assertEqual(t.run_reference('test',args)['status'],'PDF_PENDING')
                browser.assert_not_called()

    def test_zotero_failure_preserves_successful_pdf(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.zotero=True;args.zotero_base='http://127.0.0.1:23129/api';args.collection='Test'
            pdf=Path(out)/'paper.pdf';pdf.write_bytes(b'%PDF-fixture')
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(pdf,{'source':'fixture'},[])),patch.object(t.core,'ZoteroLocal',side_effect=t.core.PaperError('unavailable')):
                result=t.run_reference('test',args)
                self.assertEqual(result['status'],'PDF_SAVED')
                self.assertEqual(result['zotero'],'WRITE_PENDING')
                self.assertTrue(Path(result['pdf']).is_file())

if __name__=='__main__':unittest.main()
