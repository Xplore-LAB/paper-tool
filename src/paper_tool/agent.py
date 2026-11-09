"""Validated plan -> bounded execution -> offline status. No shell evaluation."""
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
import uuid
from urllib.parse import urlparse

from . import batch, core
from .errors import ErrorCode, PaperError, error_fields
from .safety import POLICY_VERSION, SafetyGuard, SafetyPolicy, use_guard, writer_lock

SCHEMA_VERSION='2.0'
OPTION_KEYS={'out','pdf_dir','oa_only','zotero','collection','metadata_only','zotero_base','proxy','cdp'}


def digest(data): return hashlib.sha256(data).hexdigest()

def plan_hash(data):
    return digest(json.dumps({k:v for k,v in data.items() if k!='plan_hash'},sort_keys=True,
                             ensure_ascii=False,separators=(',',':')).encode())

def _invalid(message): return PaperError(message,code=ErrorCode.INVALID_PLAN)


def _input(path):
    from .cli import read_references
    path=Path(path).expanduser().resolve(strict=True)
    raw=path.read_bytes()
    if len(raw)>10*1024*1024: raise _invalid('Reference list exceeds 10 MB')
    refs=read_references(path)
    if raw!=path.read_bytes(): raise _invalid('Reference list changed while reading')
    unique={}
    for ref in refs: unique.setdefault(batch.canonical_ref(ref),ref)
    if not unique: raise _invalid('Reference list is empty')
    return path,raw,list(unique.values())


def _validate_options(options):
    if not isinstance(options,dict) or set(options)!=OPTION_KEYS: raise _invalid('Unknown or missing task options')
    for key in ('oa_only','zotero','metadata_only'):
        if type(options[key]) is not bool: raise _invalid('Invalid boolean option: '+key)
    for key in OPTION_KEYS-{'oa_only','zotero','metadata_only'}:
        if not isinstance(options[key],str): raise _invalid('Invalid option: '+key)
    if options['zotero'] and not options['collection'].strip(): raise _invalid('An existing collection is required')
    if options['metadata_only'] and not options['zotero']: raise _invalid('Metadata-only requires Zotero')
    local=urlparse(options['zotero_base'])
    cdp=urlparse(options['cdp'])
    try:
        _=local.port,cdp.port
    except ValueError as error: raise _invalid('Invalid local endpoint port') from error
    if any(u.scheme!='http' or u.hostname not in {'localhost','127.0.0.1','::1'} or u.username or u.password or u.query or u.fragment for u in (local,cdp)):
        raise _invalid('Local integrations require loopback endpoints without credentials')
    if local.path.rstrip('/')!='/api': raise _invalid('Invalid local Zotero API path')
    if options['proxy']!='direct':
        proxy=urlparse(options['proxy'])
        if proxy.scheme not in {'http','https'} or not proxy.hostname or proxy.username or proxy.password or proxy.query or proxy.fragment:
            raise _invalid('Proxy must not contain credentials or query parameters')
    for key in ('out','pdf_dir'):
        if str(Path(options[key]).expanduser().resolve())!=options[key]: raise _invalid('Task paths must be absolute and resolved')


def make_plan(input_path,out,*,oa_only=True,zotero=False,collection='',metadata_only=False,
              zotero_base=core.BASE,proxy='direct',cdp='http://127.0.0.1:18806',pdf_dir=None,
              safety_policy=None,metadata_preflight=False):
    source,raw,refs=_input(input_path)
    out=Path(out).expanduser().resolve()
    if source in {out/name for name in ('plan.json','manifest.json','job.json','report.json','.citecargo.lock')}:
        raise _invalid('The input file cannot be a generated task artifact')
    policy=safety_policy or SafetyPolicy()
    options={'out':str(out),'pdf_dir':str(Path(pdf_dir).expanduser().resolve()) if pdf_dir else str(out/'PDF'),
             'oa_only':oa_only,'zotero':zotero,'collection':collection or '',
             'metadata_only':metadata_only,'zotero_base':zotero_base,'proxy':proxy,'cdp':cdp}
    _validate_options(options)
    preflight={'mode':'metadata' if metadata_preflight else 'offline','results':[]}
    guard=SafetyGuard(policy,allow_zotero=False)
    if metadata_preflight:
        with use_guard(guard):
            for ref in refs:
                try:
                    with guard.paper(batch.canonical_ref(ref)):
                        record,score=core.crossref_metadata(ref)
                    preflight['results'].append({'input':ref,'paper':core.paper_from_crossref(record),'confidence':score})
                except PaperError as error:
                    preflight['results'].append({'input':ref,**error_fields(error)})
                    if error.code==ErrorCode.BATCH_PAUSED: break
        preflight['safety']=guard.snapshot()
    plan={'schema_version':SCHEMA_VERSION,'policy_version':POLICY_VERSION,'kind':'PLAN',
          'job_id':uuid.uuid4().hex,'created_at':datetime.now(timezone.utc).isoformat(),
          'source':{'path':str(source),'sha256':digest(raw)},'references':refs,
          'options':options,'safety_policy':policy.to_dict(),'preflight':preflight}
    plan['plan_hash']=plan_hash(plan)
    with writer_lock(out):
        previous=batch.read_job(out)
        if previous.get('plan_hash'):
            raise _invalid('This folder already belongs to a bound job; keep its plan or choose another task folder')
        existing=out/'plan.json'
        if existing.exists():
            try:
                old=json.loads(existing.read_text(encoding='utf-8'))
                if old.get('kind')!='PLAN' or old.get('schema_version')!='2.0' or old.get('plan_hash')!=plan_hash(old):
                    raise ValueError()
            except (OSError,ValueError,TypeError,AttributeError):
                raise _invalid('An unrelated plan.json exists and was retained')
        atomic_json(out/'plan.json',plan)
    return plan


def atomic_json(path,data):
    import os,tempfile
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle: json.dump(data,handle,ensure_ascii=False,indent=2)
        os.replace(name,path)
    finally:
        if Path(name).exists(): Path(name).unlink()


def load_plan(path):
    path=Path(path).expanduser().resolve(strict=True)
    if path.stat().st_size>20*1024*1024: raise _invalid('Plan exceeds size limit')
    try: data=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError) as error: raise _invalid('Plan is unreadable') from error
    required={'schema_version','policy_version','kind','job_id','created_at','source','references','options','safety_policy','preflight','plan_hash'}
    if not isinstance(data,dict) or set(data)!=required: raise _invalid('Unknown or missing plan fields')
    if data['kind']!='PLAN' or data['schema_version']!=SCHEMA_VERSION or data['policy_version']!=POLICY_VERSION:
        raise _invalid('Unsupported plan or policy version')
    if not isinstance(data['job_id'],str) or not re.fullmatch('[a-f0-9]{32}',data['job_id']):
        raise _invalid('Invalid job identifier')
    if not isinstance(data['plan_hash'],str) or data['plan_hash']!=plan_hash(data): raise _invalid('Plan checksum does not match')
    _validate_options(data['options'])
    if path.parent!=Path(data['options']['out']): raise _invalid('Plan moved outside its intended task folder')
    try: SafetyPolicy.from_dict(data['safety_policy'])
    except ValueError as error: raise _invalid(str(error)) from error
    try: source,raw,refs=_input(data['source']['path'])
    except (OSError,KeyError,TypeError,ValueError) as error: raise _invalid('Original input is unavailable') from error
    if digest(raw)!=data['source'].get('sha256') or refs!=data['references']: raise _invalid('Input has changed since planning')
    return data


def execute_plan(path,*,allow_zotero=False,stop_token=None,event_sink=None):
    plan=load_plan(path)
    options=plan['options']
    if options['zotero'] and not allow_zotero:
        raise PaperError('This plan writes to Zotero; explicit task authorization is required',code=ErrorCode.ACCESS_DENIED)
    out=Path(options['out'])
    policy=SafetyPolicy.from_dict(plan['safety_policy'])
    with writer_lock(out):
        previous=batch.read_job(out)
        if previous.get('plan_hash') not in (None,plan['plan_hash']): raise _invalid('Job is bound to another plan')
        guard=SafetyGuard(policy,allow_zotero=options['zotero'] and allow_zotero,
                          stop_token=stop_token,event_sink=event_sink,
                          state=previous.get('safety') or plan['preflight'].get('safety'))
        job={**previous,'schema_version':SCHEMA_VERSION,'job_id':plan['job_id'],
             'plan_hash':plan['plan_hash'],'status':'RUNNING','managed':True,'stage':'pilot'}
        job['settings']={key:options[key] for key in ('zotero','collection','oa_only','metadata_only','pdf_dir')}
        job['settings']['collection']=job['settings']['collection'] or None
        batch.write_job(out,job)
        rows=batch.load_rows(out)
        batch.merge_rows(rows,plan['references'])
        batch.save_rows(out,rows)
        refs=plan['references']
        chunks=[refs[:policy.pilot_batch_size]]
        chunks.extend(refs[i:i+policy.batch_size] for i in range(policy.pilot_batch_size,len(refs),policy.batch_size))
        stop_reason=None
        result=None
        with use_guard(guard):
            for number,chunk in enumerate(chunks):
                if not chunk: continue
                result=batch.run_batch(chunk,out,zotero=options['zotero'],collection=options['collection'] or None,
                    metadata_only=options['metadata_only'],oa_only=options['oa_only'],pdf_dir=options['pdf_dir'],
                    zotero_base=options['zotero_base'],proxy=options['proxy'],cdp=options['cdp'],interval=0,
                    stream=io.StringIO())
                if guard.stop_reason:
                    stop_reason=guard.stop_reason
                    break
                if number==0 and not result['ok']:
                    stop_reason='PILOT_REVIEW'
                    break
        job=batch.read_job(out)
        complete=all(batch._succeeded(row,options['zotero'],options['metadata_only']) for row in batch.load_rows(out))
        job.update(status='PAUSED' if stop_reason else ('COMPLETED' if complete else 'PARTIAL'),
                   stage='finished' if complete else 'paused' if stop_reason else 'unfinished',
                   stop_reason=stop_reason,safety=guard.snapshot())
        batch.write_job(out,job)
        report=status(out)
        atomic_json(out/'report.json',report)
        return report


def status(out):
    from .reports import agent_report
    out=Path(out).expanduser().resolve()
    job=batch.read_job(out)
    if not job:
        plan=load_plan(out/'plan.json')
        return {'schema_version':SCHEMA_VERSION,'kind':'STATUS','job_id':plan['job_id'],'status':'PLANNED',
                'summary':{'total':len(plan['references']),'metadata_verified':0,'pdf_verified':0,
                           'archive_completed':0,'pending':len(plan['references'])},
                'stop_reason':None,'results':[],'events':[],
                'next_actions':[{'action':'run_job','job_id':plan['job_id']}]}
    return agent_report(out)
