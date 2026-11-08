"""Example: re-attach PDFs that are already on disk to existing Zotero items.

Configure with PAPER_MANIFEST / PAPER_PDF_DIR / PAPER_COLLECTION, or patch the
module-level constants. The regular ``batch`` command already does this; this
script is kept as a standalone example and as a test fixture.
"""
import json,re,os
from pathlib import Path
import paper_to_zotero as core

MANIFEST = Path(os.environ.get('PAPER_MANIFEST', 'batch/manifest.json'))
PDF_DIR = Path(os.environ.get('PAPER_PDF_DIR', 'batch/PDF'))


def main():
    rows=json.loads(MANIFEST.read_text(encoding='utf-8'))
    COL=os.environ.get('PAPER_COLLECTION','My Library/Papers')
    z=core.ZoteroLocal()
    collection=next((c for c in z.collections() if c['path']==COL),None)
    if collection is None:
        raise SystemExit('Target collection not found: '+COL+'. Set PAPER_COLLECTION to an existing full path.')
    for r in rows:
        if r.get('pdf') or not r.get('doi'):continue
        stem=re.sub(r'[^A-Za-z0-9_.-]','_',r['doi']).strip('._')
        candidates=list(PDF_DIR.glob(stem+'*.pdf'))
        if not candidates:continue
        paper=core.paper_from_crossref(core.crossref_metadata(r['doi'])[0])
        for p in candidates:
            valid,why=core.verify_pdf(p,paper)
            if not valid:continue
            key,_=z.ensure_item(paper,collection['key'])
            try:
                attachment = z.ensure_pdf(key, p, paper)
                r.update(attachment, zotero='reused', warnings='')
            except core.PaperError as error:
                r.update(status='PDF_SAVED', zotero='WRITE_PENDING', warnings=str(error))
            r.update(pdf=str(p.resolve()), zotero_key=key, paper=paper,
                     sha256=core.pdf_sha256(p), verification=why,
                     source='Local PDF recovered after strict verification')
            temp = MANIFEST.with_name(MANIFEST.name + '.tmp')
            temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            temp.replace(MANIFEST)
            print(r['number'],'RECOVERED',flush=True);break
    print('TOTAL',sum(bool(r.get('pdf')) for r in rows),flush=True)


if __name__=='__main__':
    main()
