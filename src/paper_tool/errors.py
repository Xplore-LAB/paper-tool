"""Stable error codes; text stays compatible with PaperError callers."""
from enum import Enum
import re
from urllib.parse import urlsplit

class ErrorCode(str, Enum):
    METADATA_NOT_FOUND = 'METADATA_NOT_FOUND'
    AMBIGUOUS_MATCH = 'AMBIGUOUS_MATCH'
    ACCESS_DENIED = 'ACCESS_DENIED'
    RATE_LIMITED = 'RATE_LIMITED'
    NETWORK_TIMEOUT = 'NETWORK_TIMEOUT'
    PDF_INVALID = 'PDF_INVALID'
    PDF_IDENTITY_MISMATCH = 'PDF_IDENTITY_MISMATCH'
    ZOTERO_WRITE_FAILED = 'ZOTERO_WRITE_FAILED'
    BATCH_PAUSED = 'BATCH_PAUSED'
    INVALID_PLAN = 'INVALID_PLAN'
    JOB_LOCKED = 'JOB_LOCKED'
    UNKNOWN_ERROR = 'UNKNOWN_ERROR'

ACTIONS = {
    ErrorCode.METADATA_NOT_FOUND: 'supply_doi_or_complete_citation',
    ErrorCode.AMBIGUOUS_MATCH: 'verify_authors_year_and_doi',
    ErrorCode.ACCESS_DENIED: 'ask_user_to_verify_source_access',
    ErrorCode.RATE_LIMITED: 'wait_for_retry_after',
    ErrorCode.NETWORK_TIMEOUT: 'retry_within_remaining_budget',
    ErrorCode.PDF_INVALID: 'inspect_pdf_or_try_another_authorized_source',
    ErrorCode.PDF_IDENTITY_MISMATCH: 'verify_paper_identity',
    ErrorCode.ZOTERO_WRITE_FAILED: 'check_local_zotero_and_authorized_collection',
    ErrorCode.BATCH_PAUSED: 'inspect_stop_reason_before_resuming',
    ErrorCode.INVALID_PLAN: 'recreate_plan_after_reviewing_scope',
    ErrorCode.JOB_LOCKED: 'wait_for_the_existing_writer',
    ErrorCode.UNKNOWN_ERROR: 'inspect_local_environment',
}

def safe_text(message):
    def domain(match):
        try:
            parts=urlsplit(match.group(0))
            return parts.scheme+'://'+(parts.hostname or 'source')+'/[redacted]'
        except ValueError: return '[redacted-url]'
    text=re.sub(r'https?://[^\s\x22\x27<>]+',domain,str(message))
    text=re.sub(r'(?i)\b(?:cookie|authorization|token|api[_-]?key|password)\s*[:=][^\n]*','[redacted]',text)
    return text[:1000]

class VerificationReason(str):
    """String-compatible PDF diagnostics with an explicit failure code."""
    def __new__(cls,message,code):
        value=super().__new__(cls,safe_text(message))
        value.code=ErrorCode(code)
        return value

class PaperError(Exception):
    def __init__(self,message,*,code=None,retryable=False,retry_after=None,http_status=None,source=None,stop_reason=None):
        super().__init__(safe_text(message))
        self.code=ErrorCode(code or ErrorCode.UNKNOWN_ERROR)
        self.retryable=bool(retryable)
        self.retry_after=retry_after
        self.http_status=http_status
        self.source=source
        self.stop_reason=stop_reason

    def as_dict(self):
        return {'error_code':self.code.value,'message':str(self),'retryable':self.retryable,
                'retry_after':self.retry_after,'http_status':self.http_status,
                'source':self.source,'stop_reason':self.stop_reason,'next_action':ACTIONS[self.code]}

def error_fields(error,code=None):
    if not isinstance(error,PaperError):
        error=PaperError(str(error),code=code)
    elif code is not None and error.code==ErrorCode.UNKNOWN_ERROR:
        error=PaperError(str(error),code=code,retryable=error.retryable,retry_after=error.retry_after,
                         http_status=error.http_status,source=error.source,stop_reason=error.stop_reason)
    data=error.as_dict()
    return {'error_code':data['error_code'],'error_detail':data,'next_actions':[data['next_action']]}
