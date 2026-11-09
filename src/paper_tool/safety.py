"""Task-scoped remote scheduling, stop budgets and exclusive checkpoint writers."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import asdict, dataclass, fields
from email.utils import parsedate_to_datetime
from functools import wraps
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

from .errors import ErrorCode, PaperError

POLICY_VERSION='2.0'

@dataclass(frozen=True)
class SafetyPolicy:
    max_concurrency_per_host:int=1
    min_request_interval:float=30.0
    max_retries_per_paper:int=2
    pilot_batch_size:int=5
    batch_size:int=10
    max_runtime_seconds:int=7200
    max_download_bytes:int=2*1024**3

    def __post_init__(self):
        ceilings={'max_concurrency_per_host':1,'max_retries_per_paper':2,'pilot_batch_size':5,
                  'batch_size':10,'max_runtime_seconds':7200,'max_download_bytes':2*1024**3}
        for name,limit in ceilings.items():
            value=getattr(self,name)
            if type(value) is not int or value < (0 if name=='max_retries_per_paper' else 1) or value>limit:
                raise ValueError('Invalid safety policy: '+name)
        if isinstance(self.min_request_interval,bool) or not isinstance(self.min_request_interval,(int,float)) or not math.isfinite(self.min_request_interval) or self.min_request_interval<30:
            raise ValueError('Remote request interval must be at least 30 seconds')

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)-{f.name for f in fields(cls)}:
            raise ValueError('Unknown safety policy fields')
        return cls(**data)


def local_url(url):
    return urlparse(url).hostname in {'localhost','127.0.0.1','::1'}


def source_key(url):
    host=(urlparse(url).hostname or '').lower().rstrip('.')
    for suffix,name in [('sciencedirect.com','publisher:elsevier'),('elsevier.com','publisher:elsevier'),
                        ('sciencedirectassets.com','publisher:elsevier'),('els-cdn.com','publisher:elsevier'),
                        ('crossref.org','metadata:crossref'),('openalex.org','metadata:openalex'),
                        ('unpaywall.org','metadata:unpaywall')]:
        if host==suffix or host.endswith('.'+suffix): return name
    return host.removeprefix('www.')

class Lease:
    def __init__(self,guard,key,lock): self.guard,self.key,self.lock=guard,key,lock
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def close(self):
        if self.lock is not None:
            with self.guard._mutex: self.guard._finished[self.key]=self.guard.clock()
            self.lock.release()
            self.lock=None

class SafetyGuard:
    def __init__(self,policy=None,*,stop_token=None,event_sink=None,clock=None,sleeper=None,
                 wall_clock=None,allow_zotero=None,state=None):
        self.policy=policy or SafetyPolicy()
        self.stop_token=stop_token
        self.event_sink=event_sink
        self.state_sink=None
        self.clock=clock or time.monotonic
        self.sleeper=sleeper or time.sleep
        self.wall_clock=wall_clock or time.time
        self.allow_zotero=allow_zotero
        self.started=self.clock()
        self.previous_elapsed=0.0
        self.downloaded_bytes=0
        self.stop_reason=None
        self.events=[]
        self.errors=[]
        self._mutex=threading.RLock()
        self._locks={}
        self._finished={}
        self._blocked={}
        self._cooldown={}
        self._retries={}
        self._paper=ContextVar('citecargo-paper-'+str(id(self)),default='standalone')
        if state:
            if state.get('policy_version')!=POLICY_VERSION or state.get('policy')!=self.policy.to_dict():
                raise PaperError('Stored safety policy differs from this task',code=ErrorCode.INVALID_PLAN)
            self.previous_elapsed=float(state.get('elapsed',0))
            self.downloaded_bytes=state.get('downloaded_bytes',0)
            if (not math.isfinite(self.previous_elapsed) or self.previous_elapsed<0
                    or type(self.downloaded_bytes) is not int or self.downloaded_bytes<0):
                raise PaperError('Stored runtime budget is invalid',code=ErrorCode.INVALID_PLAN)
            self._blocked=dict(state.get('blocked_sources') or {})
            self._cooldown=dict(state.get('cooldowns') or {})
            self._retries=dict(state.get('retries') or {})
            self.events=list(state.get('events') or [])[-2000:]
            for key,stamp in (state.get('last_finished') or {}).items():
                self._finished[key]=self.clock()-max(0,self.wall_clock()-float(stamp))

    @contextmanager
    def paper(self,reference):
        token=self._paper.set(str(reference).lower())
        try: yield self
        finally: self._paper.reset(token)

    def emit(self,event,**data):
        item={'event':event,**data}
        with self._mutex:
            self.events.append(item)
            self.events=self.events[-2000:]
        if self.state_sink:
            try: self.state_sink(dict(item))
            except OSError as error:
                self.stop_reason='CHECKPOINT_WRITE_FAILED'
                raise PaperError('Cannot persist task safety state',code=ErrorCode.BATCH_PAUSED,
                                 stop_reason=self.stop_reason) from error
        if self.event_sink:
            try: self.event_sink(dict(item))
            except Exception: pass  # Logging must not weaken enforcement.

    def pause(self,reason):
        if not self.stop_reason:
            self.stop_reason=reason
            self.emit('task_paused',reason=reason)
        raise PaperError('Task paused: '+self.stop_reason,code=ErrorCode.BATCH_PAUSED,stop_reason=self.stop_reason)

    def check_batch_budget(self):
        if self.stop_reason: self.pause(self.stop_reason)
        if self.stop_token is not None and self.stop_token.is_set(): self.pause('USER_CANCELLED')
        if self.previous_elapsed+self.clock()-self.started>=self.policy.max_runtime_seconds: self.pause('RUNTIME_BUDGET')
        if self.downloaded_bytes>self.policy.max_download_bytes: self.pause('DOWNLOAD_BUDGET')

    def should_stop(self):
        try: self.check_batch_budget()
        except PaperError: return True
        return False

    def wait(self,seconds):
        remaining=max(0,float(seconds))
        while remaining>0:
            self.check_batch_budget()
            step=min(1.0,remaining)
            self.sleeper(step)
            remaining-=step
        self.check_batch_budget()

    def before_request(self,url,operation):
        self.check_batch_budget()
        if operation=='zotero_write' and self.allow_zotero is False:
            raise PaperError('Zotero writes are outside this task permission',code=ErrorCode.ACCESS_DENIED)
        if local_url(url): return Lease(self,'local',None)
        key=source_key(url)
        self._check_source(key)
        with self._mutex: lock=self._locks.setdefault(key,threading.Lock())
        while not lock.acquire(blocking=False): self.wait(.1)
        try:
            self._check_source(key)
            finished=self._finished.get(key)
            if finished is not None:
                delay=max(0,self.policy.min_request_interval-(self.clock()-finished))
                if delay: self.emit('throttle',source=key,seconds=delay)
                self.wait(delay)
            self._check_source(key)
            self.emit('request',source=key,operation=operation)
            return Lease(self,key,lock)
        except BaseException:
            lock.release()
            raise

    def _check_source(self,key):
        self.check_batch_budget()
        if key in self._blocked:
            code=ErrorCode(self._blocked[key])
            raise PaperError('Source is paused for this task',code=code,source=key,
                             http_status=403 if code==ErrorCode.ACCESS_DENIED else 429 if code==ErrorCode.RATE_LIMITED else None)
        remaining=self._cooldown.get(key,0)-self.wall_clock()
        if remaining>0:
            raise PaperError('Source is cooling down',code=ErrorCode.RATE_LIMITED,retryable=True,retry_after=remaining,source=key,http_status=429)

    def after_response(self,url,status,headers):
        if local_url(url): return
        key=source_key(url)
        if status==429:
            raw=next((v for k,v in headers.items() if k.lower()=='retry-after'),None)
            try:
                delay=float(raw)
                if not math.isfinite(delay): raise ValueError()
            except (ValueError,TypeError):
                try: delay=parsedate_to_datetime(raw).timestamp()-self.wall_clock()
                except (ValueError,TypeError,OverflowError): delay=60.0
            delay=max(0,delay)
            self._cooldown[key]=self.wall_clock()+delay
            self.emit('rate_limited',source=key,http_status=status,retry_after=delay)
            error=PaperError('HTTP 429 from source',code=ErrorCode.RATE_LIMITED,retryable=True,retry_after=delay,http_status=status,source=key)
        elif status in {401,403}:
            self._blocked[key]='ACCESS_DENIED'
            self.emit('source_paused',source=key,http_status=status)
            error=PaperError(f'HTTP {status} from source',code=ErrorCode.ACCESS_DENIED,http_status=status,source=key)
        elif status>=400:
            error=PaperError(f'HTTP {status} from source',code=ErrorCode.METADATA_NOT_FOUND if status==404 else ErrorCode.NETWORK_TIMEOUT,
                             retryable=status in {408,500,502,503,504},http_status=status,source=key)
        else: return
        self.record_error(error)
        raise error

    def record_error(self,error):
        self.errors.append(error.as_dict())
        self.errors=self.errors[-200:]

    def retry_allowed(self,error):
        if not error.retryable: return False
        key=self._paper.get()
        with self._mutex:
            count=self._retries.get(key,0)
            if count>=self.policy.max_retries_per_paper:
                if error.source:
                    self._blocked[error.source]=error.code.value
                    self.emit('source_paused',source=error.source,reason='RETRY_BUDGET')
                return False
            self._retries[key]=count+1
        self.emit('retry',source=error.source,attempt=count+1)
        return True

    def consume_bytes(self,count):
        if type(count) is not int or count<0: raise ValueError('Transferred byte count must be nonnegative')
        with self._mutex: self.downloaded_bytes+=count
        self.check_batch_budget()

    def snapshot(self):
        return {'policy_version':POLICY_VERSION,'policy':self.policy.to_dict(),
                'elapsed':self.previous_elapsed+self.clock()-self.started,'downloaded_bytes':self.downloaded_bytes,
                'blocked_sources':dict(self._blocked),'cooldowns':dict(self._cooldown),'retries':dict(self._retries),
                'last_finished':{key:self.wall_clock()-max(0,self.clock()-stamp) for key,stamp in self._finished.items()},
                'stop_reason':self.stop_reason,'events':list(self.events)}

_current=ContextVar('citecargo-safety-guard',default=None)
_locks=ContextVar('citecargo-writer-locks',default=())

def current_guard(): return _current.get()

@contextmanager
def use_guard(guard):
    token=_current.set(guard)
    try: yield guard
    finally: _current.reset(token)

@contextmanager
def task_scope(policy=None,**kwargs):
    guard=current_guard()
    if guard is not None:
        yield guard
    else:
        with use_guard(SafetyGuard(policy,**kwargs)) as guard: yield guard

def task_entry(function):
    @wraps(function)
    def run(*args,**kwargs):
        with task_scope(): return function(*args,**kwargs)
    return run

def paper_entry(function):
    @wraps(function)
    def run(reference,*args,**kwargs):
        with task_scope() as guard:
            name=reference.get('doi','standalone') if isinstance(reference,dict) else str(reference)
            scope=guard.paper(name) if guard._paper.get()=='standalone' else nullcontext(guard)
            with scope: return function(reference,*args,**kwargs)
    return run

@contextmanager
def writer_lock(folder,*,enabled=True):
    if not enabled:
        yield
        return
    folder=Path(folder).expanduser().resolve()
    key=str(folder)
    if key in _locks.get():
        yield
        return
    folder.mkdir(parents=True,exist_ok=True)
    handle=(folder/'.citecargo.lock').open('a+b')
    token=None
    locked=False
    try:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0: handle.write(b'0'); handle.flush()
            handle.seek(0)
            try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError: raise PaperError('Checkpoint is in use',code=ErrorCode.JOB_LOCKED)
        else:
            import fcntl
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise PaperError('Checkpoint is in use',code=ErrorCode.JOB_LOCKED)
        locked=True
        token=_locks.set((*_locks.get(),key))
        yield
    finally:
        if token is not None: _locks.reset(token)
        if locked:
            if os.name=='nt':
                handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle,fcntl.LOCK_UN)
        handle.close()
