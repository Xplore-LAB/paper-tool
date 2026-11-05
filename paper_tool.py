#!/usr/bin/env python3
"""One command for reference resolution, authorized PDF retrieval and Zotero."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace
import time
import paper_to_zotero as core

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = Path('/home/lab434/data/papers/reference-to-zotero')


def doctor():
    checks = {}
    for name, port in (('vpn_proxy',1081),('browser_cdp',18806),('zotero_forward',23129)):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=2):
                checks[name] = True
        except OSError:
            checks[name] = False
    return {'ok': checks['vpn_proxy'] and checks['browser_cdp'], 'checks':checks,
            'note':'Listening ports only; VPN entitlement and Zotero authorization need a real request.'}


def run_reference(reference, args):
    record, confidence = core.crossref_metadata(reference)
    paper = core.paper_from_crossref(record)
    out = Path(args.out).expanduser().resolve()
    filename = re.sub(r'[^A-Za-z0-9_.-]','_',paper['doi']).strip('._')+'.pdf'
    dest = out / filename
    result = {'paper':paper,'confidence':confidence,'status':'PREVIEW','pdf':None,'warnings':[]}
    if args.command == 'preview':
        result['candidates'] = core.pdf_candidates(paper['doi'], errors=result['warnings'])
        return result
    out.mkdir(parents=True,exist_ok=True)
    path, location, errors = core.download_verified(paper,core.pdf_candidates(paper['doi'],errors=result['warnings']),out)
    result['warnings'].extend(errors)
    if path is None and not args.oa_only:
        pii = next((m.group(1) for link in record.get('link',[]) if (m:=re.search(r'/PII:([A-Z0-9]+)',link.get('URL','')))),None)
        if pii:
            candidate = dest if not dest.exists() else dest.with_name(dest.stem+'-browser.pdf')
            if candidate.exists():
                valid, _ = core.verify_pdf(candidate,paper)
                if valid:
                    path=candidate
            if path is None:
                process = subprocess.run(['node',str(ROOT/'browser_pdf.mjs'),'--pii',pii,'--out',str(candidate),'--cdp',args.cdp,'--proxy',args.proxy],capture_output=True,text=True,timeout=180)
                if process.returncode == 0 and candidate.exists():
                    valid, why = core.verify_pdf(candidate,paper)
                    if valid:
                        path=candidate
                        location={'source':'authorized_browser_via_vpn','version':'publishedVersion'}
                    else:
                        result['warnings'].append('Downloaded file needs review: '+why)
                else:
                    result['warnings'].append('Browser route needs attention; run paper-tool doctor and inspect the authorized browser.')
    if path:
        result.update(status='PDF_SAVED',pdf=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),location=location)
    else:
        result['status']='PDF_PENDING'
    if args.zotero:
        try:
            z=core.ZoteroLocal(args.zotero_base)
            selected,_=core.choose_collection(z,paper,args.collection)
            if selected is None:
                result['zotero']='COLLECTION_REVIEW'
            else:
                key,created=z.ensure_item(paper,selected['key'])
                result.update(zotero_key=key,zotero='created' if created else 'reused',collection=selected['path'])
                if path and not z.has_pdf(key):
                    result['attachment_key']=z.upload_pdf(key,path)
                    result['status']='PDF_ATTACHED'
        except core.PaperError:
            result['zotero']='WRITE_PENDING'
            result['warnings'].append('Zotero write not completed; downloaded PDF is retained.')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('doctor',help='Check VPN proxy, browser and Zotero forward')
    for command in ('fetch','preview'):
        p=commands.add_parser(command,help='Retrieve PDF' if command=='fetch' else 'Read-only metadata preview')
        p.add_argument('reference',nargs='?',help='DOI or full bibliographic reference')
        p.add_argument('--input',type=Path,help='UTF-8 references, one per line')
        p.add_argument('--out',default=str(DEFAULT_OUT))
        p.add_argument('--oa-only',action='store_true')
        p.add_argument('--proxy',default='http://127.0.0.1:1081')
        p.add_argument('--cdp',default='http://127.0.0.1:18806')
        p.add_argument('--interval',type=float,default=30,help='Pause between papers; no transfer-rate limit')
        p.add_argument('--zotero',action='store_true',help='Explicitly allow Zotero writes (fetch only)')
        p.add_argument('--zotero-base',default='http://127.0.0.1:23129/api')
        p.add_argument('--collection')
    args=parser.parse_args(argv)
    if args.command=='doctor':
        result=doctor();print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 2
    if bool(args.reference)==bool(args.input):parser.error('Supply either one reference or --input')
    if args.interval<0:parser.error('--interval cannot be negative')
    if args.command=='preview' and args.zotero:parser.error('preview never writes Zotero')
    if args.zotero:
        from urllib.parse import urlparse
        u=urlparse(args.zotero_base)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:parser.error('Zotero must use a loopback address; use SSH forwarding')
    refs=[args.reference] if args.reference else [x.strip() for x in args.input.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    refs=list(dict.fromkeys(refs))
    core.PDF_RATE_KIB=0
    results=[]
    history=[]
    report_path=Path(args.out).expanduser()/'report.json'
    if args.command=='fetch' and report_path.exists():
        try:history=json.loads(report_path.read_text()).get('results',[])
        except (OSError,ValueError):parser.error('Existing report is unreadable; choose another output folder')
    for i,ref in enumerate(refs):
        if i and args.command=='fetch':time.sleep(args.interval)
        try:result=run_reference(ref,args)
        except (core.PaperError,OSError,ValueError,subprocess.TimeoutExpired) as error:
            result={'status':'NEEDS_REVIEW','error':type(error).__name__}
        result['input']=ref
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if args.command=='fetch':
            target=Path(args.out).expanduser();target.mkdir(parents=True,exist_ok=True)
            merged={r.get('paper',{}).get('doi') or r.get('input'):r for r in history+results}
            temp=target/'report.json.tmp';temp.write_text(json.dumps({'results':list(merged.values())},ensure_ascii=False,indent=2));temp.replace(target/'report.json')
    good={'PDF_SAVED','PDF_ATTACHED'} if args.command=='fetch' else {'PREVIEW'}
    return 0 if results and all(r['status'] in good and r.get('zotero') not in {'COLLECTION_REVIEW','WRITE_PENDING'} for r in results) else 2

if __name__=='__main__':
    raise SystemExit(main())
