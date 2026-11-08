"""Run the real Node file-saving path against a fake Playwright connection."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from paper_tool import cli as paper_tool


@unittest.skipUnless(shutil.which('node'), 'Node is optional for OA-only downloads')
class BrowserFileTests(unittest.TestCase):
    def run_backend(self, folder, *, fail=False, race=False):
        fake = Path(folder) / 'fake.cjs'
        fake.write_text('''
const fs=require('node:fs');
const payload=Buffer.from('%PDF-test-browser-body');
const pdf={waitForURL:async()=>{},title:async()=>'PDF',evaluate:async(fn,n)=>{
 if(typeof n==='number'){
  if(process.env.TEST_FAIL==='1')throw new Error('transfer interrupted');
  return payload.subarray(n,n+32768).toString('base64');
 }
 return {bytes:payload.length};
}};
const page={goto:async()=>{},waitForFunction:async()=>{},waitForEvent:async()=>pdf,
 locator:()=>({filter:()=>({first:()=>({click:async()=>{}})})}),title:async()=>'Article'};
const context={newPage:async()=>page,close:async()=>{}};
module.exports={chromium:{connectOverCDP:async()=>{
 if(process.env.TEST_RACE==='1')fs.writeFileSync(process.env.TEST_OUT,'other-process-output');
 return {contexts:()=>[context],newContext:async()=>context,close:async()=>{}};
}}};
''')
        output = Path(folder) / 'p.pdf'
        env = dict(os.environ, PLAYWRIGHT_CORE_PATH=str(fake), TEST_FAIL=str(int(fail)),
                   TEST_RACE=str(int(race)), TEST_OUT=str(output))
        # Force the explicit fake even if a real Playwright exists in node_modules.
        helper = paper_tool.ROOT / 'browser' / 'download.mjs'
        isolated = Path(folder) / 'browser_pdf.mjs'
        isolated.write_bytes(helper.read_bytes())
        result = subprocess.run(['node', str(isolated), '--pii', 'S0020025526007310',
                                 '--out', str(output), '--proxy', 'direct'],
                                cwd=folder, env=env, capture_output=True, text=True, timeout=10)
        return output, result

    def test_stale_partial_does_not_block_a_successful_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            stale = Path(folder) / 'p.pdf.part'
            stale.write_bytes(b'previous-interrupted-run')
            output, result = self.run_backend(folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
            self.assertEqual(output.read_bytes(), b'%PDF-test-browser-body')
            self.assertEqual(stale.read_bytes(), b'previous-interrupted-run')
            self.assertEqual(list(Path(folder).glob('*.part')), [stale])

    def test_transfer_failure_cleans_only_its_own_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            output, result = self.run_backend(folder, fail=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).glob('*.part')), [])

    def test_racing_output_is_retained_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output, result = self.run_backend(folder, race=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b'other-process-output')
            self.assertEqual(list(Path(folder).glob('*.part')), [])
