"""Deterministic scheduling and budget tests: no network, no real sleeps."""
import threading
import unittest
from paper_tool.errors import ErrorCode, PaperError
from paper_tool.safety import SafetyGuard, SafetyPolicy, use_guard, current_guard

class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds

class SafetyTests(unittest.TestCase):
    def guard(self, **kwargs):
        clock = Clock()
        return SafetyGuard(clock=clock, sleeper=clock.sleep, wall_clock=lambda: 1000+clock.now, **kwargs), clock

    def test_same_source_aliases_wait_after_completion(self):
        guard, clock = self.guard()
        with guard.before_request('https://www.sciencedirect.com/a?x=1', 'pdf'):
            clock.sleep(2)
        with guard.before_request('https://api.elsevier.com/different', 'metadata'): pass
        self.assertEqual(clock.now, 32)
        with guard.before_request('https://api.openalex.org/works', 'metadata'): pass
        self.assertEqual(clock.now, 32)

    def test_429_honors_retry_after_and_does_not_make_repeated_requests(self):
        guard, clock = self.guard()
        with self.assertRaises(PaperError) as first:
            guard.after_response('https://publisher.test/a', 429, {'Retry-After':'75'})
        self.assertEqual(first.exception.code, ErrorCode.RATE_LIMITED)
        with self.assertRaises(PaperError):
            guard.before_request('https://publisher.test/other', 'pdf')
        clock.sleep(74)
        with self.assertRaises(PaperError): guard.before_request('https://publisher.test/b','pdf')
        clock.sleep(1)
        with guard.before_request('https://publisher.test/c','pdf'): pass

    def test_403_suspends_only_that_source(self):
        guard, _ = self.guard()
        with self.assertRaises(PaperError): guard.after_response('https://www.sciencedirect.com/a',403,{})
        with self.assertRaises(PaperError) as error: guard.before_request('https://api.elsevier.com/b','pdf')
        self.assertEqual(error.exception.code, ErrorCode.ACCESS_DENIED)
        with guard.before_request('https://repository.test/paper.pdf','pdf'): pass
        self.assertFalse(guard.should_stop())

    def test_retries_are_shared_per_paper_not_per_url(self):
        guard, _ = self.guard()
        error=PaperError('timeout',code=ErrorCode.NETWORK_TIMEOUT,retryable=True)
        with guard.paper('one'):
            self.assertTrue(guard.retry_allowed(error))
            self.assertTrue(guard.retry_allowed(error))
            self.assertFalse(guard.retry_allowed(error))
        with guard.paper('two'): self.assertTrue(guard.retry_allowed(error))

    def test_cancel_runtime_and_transfer_budgets_stop(self):
        event=threading.Event()
        guard, clock=self.guard(stop_token=event)
        event.set()
        with self.assertRaises(PaperError) as error: guard.check_batch_budget()
        self.assertEqual(error.exception.stop_reason,'USER_CANCELLED')
        guard, clock=self.guard(policy=SafetyPolicy(max_runtime_seconds=40,max_download_bytes=100))
        guard.consume_bytes(99)
        with self.assertRaises(PaperError): guard.consume_bytes(2)
        self.assertEqual(guard.stop_reason,'DOWNLOAD_BUDGET')
        guard, clock=self.guard(policy=SafetyPolicy(max_runtime_seconds=40))
        clock.sleep(40)
        with self.assertRaises(PaperError): guard.before_request('https://p.test/a','pdf')
        self.assertEqual(guard.stop_reason,'RUNTIME_BUDGET')

    def test_local_api_is_separate_but_write_permission_is_checked(self):
        guard, clock=self.guard(allow_zotero=False)
        for _ in range(4):
            with guard.before_request('http://127.0.0.1:23119/api','zotero_read'): pass
        self.assertEqual(clock.now,0)
        with self.assertRaises(PaperError): guard.before_request('http://127.0.0.1:23119/api','zotero_write')

    def test_policy_cannot_relax_the_floor_or_silently_accept_unknown_fields(self):
        for kwargs in ({'min_request_interval':0},{'max_concurrency_per_host':2},{'max_retries_per_paper':3},{'max_runtime_seconds':True}):
            with self.assertRaises(ValueError): SafetyPolicy(**kwargs)
        with self.assertRaises(ValueError): SafetyPolicy.from_dict({'unknown':1})

    def test_task_context_and_state_restore(self):
        guard, clock=self.guard()
        with use_guard(guard): self.assertIs(current_guard(),guard)
        self.assertIsNone(current_guard())
        with self.assertRaises(PaperError): guard.after_response('https://blocked.test/a',403,{})
        guard.consume_bytes(10)
        restored, _=self.guard(state=guard.snapshot())
        self.assertEqual(restored.downloaded_bytes,10)
        with self.assertRaises(PaperError): restored.before_request('https://blocked.test/b','pdf')

    def test_error_output_redacts_credentials_and_signed_urls(self):
        from paper_tool.errors import error_fields
        error=PaperError('failed https://user:password@pub.test/pdf?token=secret#x Cookie: auth=secret',code=ErrorCode.ACCESS_DENIED)
        self.assertNotIn('password',str(error))
        self.assertNotIn('secret',str(error))
        self.assertEqual(error.as_dict()['error_code'],'ACCESS_DENIED')
        self.assertEqual(error_fields(PaperError('upload interrupted'),ErrorCode.ZOTERO_WRITE_FAILED)['error_code'],
                         'ZOTERO_WRITE_FAILED')

class TransportSafetyTests(unittest.TestCase):
    def test_403_is_enforced_before_a_second_open(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import MagicMock,patch
        from paper_tool import core
        guard=SafetyGuard()
        opener=MagicMock()
        opener.open.side_effect=HTTPError('https://source.test/p?token=secret',403,'Denied',{},io.BytesIO(b'Cookie: secret'))
        with use_guard(guard),patch.object(core,'build_opener',return_value=opener):
            for url in ('https://source.test/one','https://source.test/two'):
                with self.assertRaises(PaperError) as error: core.request_bytes('GET',url)
                self.assertEqual(error.exception.code,ErrorCode.ACCESS_DENIED)
                self.assertNotIn('secret',str(error.exception))
        self.assertEqual(opener.open.call_count,1)

    def test_429_retry_waits_without_real_sleep(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import MagicMock,patch
        from paper_tool import core
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self): return 'https://source.test/p'
        clock=Clock();guard=SafetyGuard(clock=clock,sleeper=clock.sleep,wall_clock=lambda:1000+clock.now)
        opener=MagicMock()
        opener.open.side_effect=[HTTPError('https://source.test/p',429,'Slow',{'Retry-After':'75'},io.BytesIO()),Response(b'{}')]
        with use_guard(guard),patch.object(core,'build_opener',return_value=opener):
            self.assertEqual(core.get_json('https://source.test/p'),{})
        self.assertEqual(opener.open.call_count,2)
        self.assertGreaterEqual(clock.now,75)

    def test_redirect_hops_also_pass_through_guard(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import MagicMock,patch
        from paper_tool import core
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self): return 'https://source.test/final'
        clock=Clock();guard=SafetyGuard(clock=clock,sleeper=clock.sleep)
        opener=MagicMock()
        opener.open.side_effect=[HTTPError('https://source.test/a',302,'Redirect',{'Location':'/final'},io.BytesIO()),Response(b'{}')]
        with use_guard(guard),patch.object(core,'build_opener',return_value=opener): core.get_json('https://source.test/a')
        self.assertEqual(opener.open.call_count,2)
        self.assertEqual(clock.now,30)

    def test_wrong_paper_is_never_published_as_a_saved_pdf(self):
        import io,tempfile
        from pathlib import Path
        from unittest.mock import MagicMock,patch
        from paper_tool import core
        from tests.test_workflows import make_pdf
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self): return 'https://repository.test/paper.pdf'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=make_pdf(root/'other.pdf','Unrelated quantum optics experiment').read_bytes()
            opener=MagicMock();opener.open.return_value=Response(raw)
            guard=SafetyGuard()
            with use_guard(guard),patch.object(core,'build_opener',return_value=opener):
                pdf,_,_=core.download_verified({'doi':'10.1000/target','title':'A verified paper about oxygen supply networks','authors':[]},
                    [{'url':'https://repository.test/paper.pdf','source':'test'}],root/'out')
            self.assertIsNone(pdf)
            self.assertFalse(list((root/'out').glob('*.pdf')))
            self.assertEqual(guard.errors[-1]['error_code'],'PDF_IDENTITY_MISMATCH')

    def test_racing_destination_is_preserved(self):
        import io,tempfile
        from pathlib import Path
        from unittest.mock import MagicMock,patch
        from paper_tool import core
        from tests.test_workflows import make_pdf
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self): return 'https://repository.test/paper.pdf'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=make_pdf(root/'seed.pdf').read_bytes()
            dest=root/'out/10.1000_target.pdf'
            opener=MagicMock();opener.open.return_value=Response(raw)
            real_link=core.os.link
            def race(source,target):
                Path(target).write_bytes(b'user file, keep it')
                return real_link(source,target)
            with patch.object(core,'build_opener',return_value=opener),patch.object(core.os,'link',side_effect=race):
                result,_,_=core.download_verified({'doi':'10.1000/target','title':'A verified paper about oxygen supply networks','authors':[]},
                    [{'url':'https://repository.test/paper.pdf','source':'test'}],root/'out')
            self.assertIsNone(result)
            self.assertEqual(dest.read_bytes(),b'user file, keep it')

    def test_missing_or_mismatched_metadata_has_stable_codes(self):
        from unittest.mock import patch
        from paper_tool import core
        for payload in ([],{}, {'message':None},{'message':{}}):
            with self.subTest(payload=payload),patch.object(core,'get_json',return_value=payload),self.assertRaises(PaperError) as error:
                core.crossref_metadata('10.1000/requested')
            self.assertEqual(error.exception.code,ErrorCode.METADATA_NOT_FOUND)
        with patch.object(core,'get_json',return_value={'message':{'DOI':'10.1000/other','title':['Other paper']}}),self.assertRaises(PaperError) as error:
            core.crossref_metadata('10.1000/requested')
        self.assertEqual(error.exception.code,ErrorCode.AMBIGUOUS_MATCH)
