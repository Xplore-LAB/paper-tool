#!/usr/bin/env python3
"""Reference text -> verified metadata -> legal OA PDF -> existing Zotero collection.

Shared library used by ``paper_tool.py``. Except for pypdf (PDF identity
verification) it only depends on the Python standard library. The preferred
entry point is ``python paper_tool.py <command>``; the legacy ``--apply``
CLI in this file is kept for backwards compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen, build_opener, ProxyHandler, url2pathname
import uuid

BASE = "http://127.0.0.1:23119/api"
DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?(10\.\d{4,9}/[^\s,;<>]+)", re.I)
WORDS = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = set("the and for with from into using based through model method long term new study data research paper analysis of to in on a an by".split())
MAX_PDF = 60 * 1024 * 1024
CONFERENCE_TYPES = {"proceedings-article", "proceedings", "conference-paper"}
PDF_PROXY = None
PDF_URLS = []
PDF_RATE_KIB = 0.0
PDF_INTERVAL = 30.0
LAST_PDF_ATTEMPT = None


class PaperError(Exception):
    pass


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def tokens(text: str) -> set[str]:
    return {x for x in WORDS.findall(normalized(text)) if x not in STOPWORDS}


def doi_from(text: str) -> str | None:
    match = DOI_RE.search(text or "")
    return match.group(1).rstrip(".);]").lower() if match else None


def match_score(reference: str, record: dict) -> float:
    """Conservative citation match: title is indispensable, year/author help."""
    title = (record.get("title") or [""])[0]
    phrase = normalized(title)
    haystack = normalized(reference)
    if not phrase:
        return 0.0
    if phrase in haystack:
        title_score = 1.0
    else:
        ws = phrase.split()
        title_score = sum(word in haystack.split() for word in ws) / max(1, len(ws))
    authors = record.get("author") or []
    author_match = bool(authors and normalized(authors[0].get("family", "")) in haystack.split())
    year = str(((record.get("published") or {}).get("date-parts") or [[""]])[0][0])
    year_match = year in reference
    journal = normalized((record.get("container-title") or [""])[0])
    journal_match = bool(journal and journal in haystack)
    return round(0.72 * title_score + 0.10 * int(author_match) + 0.08 * int(year_match) + 0.10 * int(journal_match), 4)


def request_bytes(method: str, url: str, *, payload=None, headers=None, timeout=22):
    req = Request(url, data=payload, method=method, headers={"User-Agent": "ReferenceToZoteroMVP/0.1 personal-research", **(headers or {})})
    try:
        opener = build_opener(ProxyHandler({})) if urlparse(url).hostname in {"localhost", "127.0.0.1", "::1"} else build_opener()
        with opener.open(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(), response.geturl()
    except HTTPError as error:
        body = error.read(4096)
        raise PaperError(f"HTTP {error.code} on {urlparse(url).netloc}: {body[:160]!r}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PaperError(f"Network failure for {urlparse(url).netloc}: {error}") from error


def get_json(url: str, *, headers=None) -> dict | list:
    _status, _headers, content, _final = request_bytes("GET", url, headers=headers)
    try:
        return json.loads(content)
    except ValueError as error:
        raise PaperError(f"Invalid JSON returned by {urlparse(url).netloc}") from error


def crossref_metadata(reference: str, *, demo=False) -> tuple[dict, float]:
    if demo:
        return SAMPLE_RECORD.copy(), 1.0
    doi = doi_from(reference)
    if doi:
        url = "https://api.crossref.org/works/" + quote(doi, safe="/")
        record = get_json(url)["message"]
        # An incorrect pasted DOI must not silently override a supplied title.
        confidence = match_score(reference, record)
        if len(tokens(reference)) >= 7 and confidence < 0.86:
            raise PaperError(f"DOI matches a different bibliographic record (score={confidence:.2f})")
        return record, 1.0 if len(tokens(reference)) < 7 else confidence
    url = "https://api.crossref.org/works?" + urlencode({"query.bibliographic": reference, "rows": 5})
    candidates = get_json(url).get("message", {}).get("items", [])
    ranked = sorted(((match_score(reference, x), x) for x in candidates), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 0.87 or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.07):
        options = [(round(s, 2), x.get("DOI"), (x.get("title") or [""])[0]) for s, x in ranked[:3]]
        raise PaperError(f"Citation match needs review; candidates={options}")
    return ranked[0][1], ranked[0][0]


def paper_from_crossref(rec: dict) -> dict:
    date_parts = (rec.get("published") or rec.get("issued") or {}).get("date-parts") or [[""]]
    event = rec.get("event") or {}
    return {
        "title": (rec.get("title") or [""])[0],
        "doi": (rec.get("DOI") or "").lower(),
        "authors": [{"first": a.get("given", ""), "last": a.get("family", "")} for a in rec.get("author", [])],
        "journal": (rec.get("container-title") or [""])[0],
        "year": str(date_parts[0][0]),
        "volume": rec.get("volume", ""),
        "issue": rec.get("issue", ""),
        "pages": rec.get("page") or rec.get("article-number") or "",
        "url": rec.get("URL") or ("https://doi.org/" + rec.get("DOI", "")),
        "type": rec.get("type") or "",
        "event_name": event.get("name") or "",
        "event_acronym": event.get("acronym") or "",
        "event_place": event.get("location") or "",
    }


def paper_from_zotero(item: dict) -> dict:
    """Rebuild the standard paper dict from an existing Zotero item.

    When a DOI is already in the library the bibliographic record is available
    locally, so the metadata-only path needs no Crossref request at all.
    """
    authors = [{"first": c.get("firstName", ""), "last": c.get("lastName", "")}
               for c in (item.get("creators") or [])
               if c.get("creatorType") == "author"]
    year = re.search(r"(?:19|20)\d{2}", str(item.get("date") or ""))
    conference = item.get("itemType") == "conferencePaper"
    doi = str(item.get("DOI") or "").lower()
    return {
        "title": item.get("title") or "",
        "doi": doi,
        "authors": authors,
        "journal": item.get("proceedingsTitle") or item.get("publicationTitle") or "",
        "year": year.group(0) if year else "",
        "volume": item.get("volume", ""),
        "issue": item.get("issue", ""),
        "pages": item.get("pages", ""),
        "url": item.get("url") or ("https://doi.org/" + doi),
        "type": "proceedings-article" if conference else "journal-article",
        "event_name": item.get("conferenceName") or "",
        "event_acronym": item.get("conferenceName") or "",
        "event_place": item.get("eventPlace") or "",
    }


def pdf_candidates(doi: str, *, demo=False, errors=None) -> list[dict]:
    """Only OA locations. Neither paywalls nor authenticated sites are scraped."""
    if demo:
        return []
    found: list[dict] = []
    if doi.lower().startswith("10.1371/journal.pone."):
        found.append({"url": "https://journals.plos.org/plosone/article/file?" + urlencode({"id": doi, "type": "printable"}),
                      "source": "PLOS_open_access", "version": "publishedVersion", "license": "cc-by"})
    key = os.environ.get("OPENALEX_API_KEY", "")
    url = "https://api.openalex.org/works/doi:" + quote(doi, safe="/")
    if key:
        url += "?" + urlencode({"api_key": key})
    try:
        work = get_json(url)
        locations = [work.get("best_oa_location")] + (work.get("locations") or [])
        for loc in locations:
            if isinstance(loc, dict) and loc.get("is_oa") and loc.get("pdf_url"):
                found.append({"url": loc["pdf_url"], "source": "OpenAlex", "version": loc.get("version") or "unknown", "license": loc.get("license")})
    except PaperError as err:
        if errors is not None:
            errors.append("OpenAlex lookup unavailable: " + str(err))
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    if email:
        try:
            data = get_json("https://api.unpaywall.org/v2/" + quote(doi, safe="/") + "?" + urlencode({"email": email}))
            for loc in [data.get("best_oa_location")] + (data.get("oa_locations") or []):
                if isinstance(loc, dict) and loc.get("url_for_pdf"):
                    found.append({"url": loc["url_for_pdf"], "source": "Unpaywall", "version": loc.get("version") or "unknown", "license": loc.get("license")})
        except PaperError as err:
            if errors is not None:
                errors.append("Unpaywall lookup unavailable: " + str(err))
    seen = set()
    unique = []
    for candidate in found:
        if candidate["url"] not in seen:
            seen.add(candidate["url"])
            unique.append(candidate)
    return unique


def safe_pdf_url(url: str) -> bool:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return False
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def verify_pdf(path: Path, paper: dict) -> tuple[bool, str]:
    """Verify format and bibliographic identity; no uncertain PDF is attached."""
    try:
        with path.open("rb") as f:
            if not f.read(5) == b"%PDF-":
                return False, "Not a PDF file"
        from pypdf import PdfReader
        reader = PdfReader(str(path), strict=False)
        if not reader.pages:
            return False, "PDF has no pages"
        text = reader.pages[0].extract_text() or ""
        if not text.strip():
            return False, "Scanned/unreadable PDF: manual review required"
        content = normalized(text)
        normalized_doi = normalized(paper["doi"])
        title_words = normalized(paper["title"]).split()
        pdf_words = content.split()
        size = len(title_words)
        if size and size <= len(pdf_words):
            best = max(
                sum(left == right for left, right in zip(title_words, pdf_words[i:i + size])) / size
                for i in range(len(pdf_words) - size + 1)
            )
        else:
            best = 0
        if best >= 0.87:
            return True, "First-page title verified" + ("; DOI also present" if normalized_doi and normalized_doi in content else "")
        # Some publisher PDFs extract every word without spaces. Still require
        # an exact full title near the top, the DOI, and the first author's name.
        compact = content.replace(" ", "")
        title = "".join(title_words)
        authors = paper.get("authors") or []
        author = normalized(authors[0].get("first", "") + authors[0].get("last", "")).replace(" ", "") if authors else ""
        if (len(title) >= 40 and title in compact[:2000] and author and author in compact
                and normalized_doi and normalized_doi.replace(" ", "") in compact):
            return True, "Exact first-page title, DOI and author verified after removing extraction spaces"
        return False, f"PDF identity unclear (contiguous title similarity={best:.2f})"
    except ImportError:
        return False, "Install pypdf to verify PDF identity"
    except Exception as error:
        return False, f"Unreadable PDF: {error}"


def pdf_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_pdf_valid(row: dict) -> bool:
    """Trust a previously verified file only while its bytes remain unchanged.

    Legacy checkpoints without a digest must pass identity verification again.
    This check never contacts Zotero or a metadata service.
    """
    pdf = row.get('pdf')
    if not pdf:
        return False
    path = Path(pdf)
    try:
        if not path.is_file():
            return False
        with path.open('rb') as handle:
            if handle.read(5) != b'%PDF-':
                return False
        digest = row.get('sha256')
        if digest:
            return pdf_sha256(path) == digest
        paper = row.get('paper') or row
        if not paper.get('doi') or not paper.get('title'):
            return False
        return verify_pdf(path, paper)[0]
    except OSError:
        return False


def download_verified(paper: dict, candidates: list[dict], out: Path) -> tuple[Path | None, dict | None, list[str]]:
    global LAST_PDF_ATTEMPT
    failures = []
    out.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", paper["doi"]).strip("._") or "unknown"
    dest = out / f"{safe_name}.pdf"
    if dest.exists():
        ok, why = verify_pdf(dest, paper)
        if ok:
            return dest, {"source": "existing_local", "version": "unknown", "url": ""}, failures
        failures.append(f"Existing file kept; could not reuse: {why}")
        # Preserve user files. Use a separate file name for newly downloaded data.
        dest = out / f"{safe_name}_{uuid.uuid4().hex[:6]}.pdf"
    for loc in candidates:
        url = loc["url"]
        if not safe_pdf_url(url):
            failures.append("Rejected non-public/non-HTTPS PDF URL")
            continue
        fd, temp_path = tempfile.mkstemp(prefix="paper-", suffix=".part", dir=out)
        os.close(fd)
        tmp = Path(temp_path)
        try:
            if LAST_PDF_ATTEMPT is not None:
                time.sleep(max(0, PDF_INTERVAL - (time.monotonic() - LAST_PDF_ATTEMPT)))
            started = time.monotonic()
            req = Request(url, headers={"User-Agent": "ReferenceToZoteroMVP/0.1 personal-research"})
            opener = build_opener(ProxyHandler({"http": PDF_PROXY, "https": PDF_PROXY} if PDF_PROXY else {}))
            with opener.open(req, timeout=25) as res, tmp.open("wb") as f:
                if not safe_pdf_url(res.geturl()):
                    raise PaperError("Redirected to an unsafe URL")
                count = 0
                while True:
                    chunk = res.read(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > MAX_PDF:
                        raise PaperError("PDF exceeds 60 MB limit")
                    f.write(chunk)
                    if PDF_RATE_KIB > 0:
                        time.sleep(max(0, count / (PDF_RATE_KIB * 1024) - (time.monotonic() - started)))
            ok, reason = verify_pdf(tmp, paper)
            if not ok:
                raise PaperError(reason)
            tmp.replace(dest)
            return dest, loc, failures
        except (PaperError, HTTPError, URLError, TimeoutError, OSError) as error:
            failures.append(f"{loc['source']} PDF unsuccessful: {error}")
        finally:
            LAST_PDF_ATTEMPT = time.monotonic()
            if tmp.exists():
                tmp.unlink()
    return None, None, failures


class ZoteroLocal:
    """Zotero 10+ local API. Never creates a collection or deletes an item."""

    def __init__(self, base=BASE):
        self.base = base.rstrip("/")
        self.key = os.environ.get("ZOTERO_LOCAL_API_KEY", "")
        self.server_id = None
        self._items_cache = None
        self._collections_cache = None
        self._connect()
        if not self.key:
            from local_auth_cache import load
            self.key = load(self.server_id)

    def _connect(self):
        _status, headers, _body, _url = request_bytes("GET", self.base + "/")
        self.server_id = next((v for k, v in headers.items() if k.lower() == "zotero-server-id"), None)
        if not self.server_id:
            raise PaperError("Zotero must be running as Zotero 10+ with the local API enabled")

    def call(self, method: str, endpoint: str, data=None, *, headers=None, _retry=True):
        hdr = {"Zotero-Server-ID": self.server_id, **(headers or {})}
        if method != "GET" and self.key:
            hdr["Zotero-API-Key"] = self.key
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
            hdr["Content-Type"] = "application/json"
        try:
            status, response_headers, body, _final = request_bytes(method, self.base + endpoint, payload=data, headers=hdr)
        except PaperError as error:
            if method != "GET" and _retry and "HTTP 401" in str(error):
                self.authorize()
                return self.call(method, endpoint, data, headers=hdr, _retry=False)
            raise
        return json.loads(body) if body else {}, response_headers

    def authorize(self):
        payload = json.dumps({"appName": "Reference-to-PDF Zotero MVP"}).encode()
        _s, _h, body, _url = request_bytes("POST", self.base + "/local/authorize", payload=payload, headers={"Content-Type": "application/json", "Zotero-Server-ID": self.server_id}, timeout=300)
        authorization = json.loads(body)
        self.key = authorization["key"]
        if authorization.get("remember"):
            from local_auth_cache import save
            save(self.server_id, self.key)

    def collections(self) -> list[dict]:
        cached = getattr(self, "_collections_cache", None)
        if cached is not None:
            return list(cached)
        raw = self.all_pages("/users/0/collections")
        entries = [x.get("data", x) for x in raw]
        by_key = {x["key"]: x for x in entries}
        def path(x):
            names = [x["name"]]
            seen = {x["key"]}
            parent = x.get("parentCollection")
            while parent and parent in by_key and parent not in seen:
                seen.add(parent)
                x = by_key[parent]
                names.insert(0, x["name"])
                parent = x.get("parentCollection")
            return "/".join(names)
        result = [{"key": c["key"], "name": c["name"], "path": path(c)} for c in entries]
        self._collections_cache = result
        return list(result)

    def items(self) -> list[dict]:
        cached = getattr(self, "_items_cache", None)
        if cached is not None:
            return list(cached)
        raw = self.all_pages("/users/0/items?itemType=-attachment")
        result = [x.get("data", x) for x in raw
                  if x.get("data", x).get("itemType") not in {"attachment", "note", "annotation"}]
        self._items_cache = result
        return list(result)

    def collection_items(self, collection_key: str) -> list[dict]:
        raw, _ = self.call("GET", f"/users/0/collections/{collection_key}/items?itemType=-attachment&limit=40")
        return [x.get("data", x) for x in raw if x.get("data", x).get("itemType") not in {"attachment", "note"}]

    def children(self, key: str) -> list[dict]:
        raw = self.all_pages(f"/users/0/items/{key}/children")
        return [x.get("data", x) for x in raw]

    def all_pages(self, endpoint):
        result = []
        sep = "&" if "?" in endpoint else "?"
        for start in range(0, 100000, 100):
            page, _ = self.call("GET", endpoint + sep + urlencode({"limit": 100, "start": start}))
            if not isinstance(page, list):
                raise PaperError("Unexpected Zotero list response")
            result.extend(page)
            if len(page) < 100:
                return result
        raise PaperError("Zotero pagination limit reached")

    def write_item(self, item: dict) -> str:
        raw, _ = self.call("POST", "/users/0/items", [item], headers={"Zotero-Write-Token": uuid.uuid4().hex})
        saved = (raw.get("successful") or {}).get("0")
        if not saved:
            raise PaperError(f"Zotero rejected new item: {raw.get('failed')}")
        data = saved.get("data") or saved
        cache = getattr(self, "_items_cache", None)
        if cache is not None and data.get("itemType") not in {"attachment", "note", "annotation"}:
            cache.append(data)
        return data["key"]

    def ensure_item(self, paper: dict, collection_key: str) -> tuple[str, bool]:
        existing = next((x for x in self.items() if x.get("DOI", "").lower() == paper["doi"]), None)
        if existing:
            if collection_key not in (existing.get("collections") or []):
                merged = list(dict.fromkeys([*(existing.get("collections") or []), collection_key]))
                _, headers = self.call("PATCH", f"/users/0/items/{existing['key']}", {"collections": merged, "version": existing["version"]})
                existing["collections"] = merged
                version = next((v for k, v in headers.items()
                                if k.lower() == 'last-modified-version'), None)
                if version is not None:
                    existing['version'] = int(version)
                else:
                    # A later PATCH must reload versions rather than reuse stale data.
                    self._items_cache = None
            return existing["key"], False
        is_conference = str(paper.get("type") or "").lower() in CONFERENCE_TYPES
        entry = {
            "itemType": "conferencePaper" if is_conference else "journalArticle",
            "title": paper["title"], "DOI": paper["doi"], "date": paper["year"],
            "volume": paper["volume"], "issue": paper["issue"], "pages": paper["pages"],
            "url": paper["url"], "collections": [collection_key],
            "creators": [{"creatorType": "author", "firstName": x["first"], "lastName": x["last"]} for x in paper["authors"]],
            "tags": [],
        }
        if is_conference:
            entry["proceedingsTitle"] = paper["journal"]
            entry["conferenceName"] = paper.get("event_acronym") or paper.get("event_name") or ""
            if paper.get("event_place"):
                entry["eventPlace"] = paper["event_place"]
        else:
            entry["publicationTitle"] = paper["journal"]
        return self.write_item(entry), True

    def has_pdf(self, key: str) -> bool:
        return any(x.get("itemType") == "attachment" and (x.get("contentType") == "application/pdf" or str(x.get("filename", "")).lower().endswith(".pdf")) for x in self.children(key))

    def ensure_pdf(self, parent_key: str, pdf: Path, paper: dict) -> dict:
        """Verify a live attachment, or resume a missing stored-file upload.

        A remote file:// path belongs to the Zotero computer. Do not mistake it
        for a missing local file. Matching MD5s can be checked by Zotero itself
        using phase one of its upload protocol, including over SSH forwarding.
        """
        health = attachment_health(self, parent_key, paper)
        attachments = health['pdf_attachments']
        for item in attachments:
            if item.get('verified'):
                return {'status': 'PDF_ALREADY_PRESENT',
                        'attachment_key': item['attachment_key']}
        md5 = hashlib.md5(pdf.read_bytes()).hexdigest()
        for item in attachments:
            if item.get('linkMode') not in {'imported_file', 'imported_url'}:
                continue
            if item.get('missing') or (item.get('state') == 'UNVERIFIED'
                                       and item.get('md5') == md5):
                uploaded = self._upload_pdf_file(item['attachment_key'], pdf,
                                                 previous_md5=item.get('md5'))
                return {'status': 'PDF_ATTACHED' if uploaded else 'PDF_ALREADY_PRESENT',
                        'attachment_key': item['attachment_key']}
        if attachments:
            raise PaperError('Existing PDF attachment cannot be verified or safely repaired; '
                             'retained without overwriting. Run audit on the Zotero computer.')
        return {'status': 'PDF_ATTACHED', 'attachment_key': self.upload_pdf(parent_key, pdf)}

    def upload_pdf(self, parent_key: str, pdf: Path) -> str:
        attachment_key = self.write_item({"itemType": "attachment", "parentItem": parent_key, "linkMode": "imported_file", "title": "PDF", "contentType": "application/pdf", "filename": pdf.name, "tags": []})
        self._upload_pdf_file(attachment_key, pdf)
        return attachment_key

    def _upload_pdf_file(self, attachment_key: str, pdf: Path, *, previous_md5=None) -> bool:
        """Upload to an existing record; return False if Zotero confirms the MD5.

        Reuse the same precondition in authorization and registration, so another
        application's attachment changes are never silently overwritten.
        """
        md5 = hashlib.md5(pdf.read_bytes()).hexdigest()
        data = urlencode({"md5": md5, "filename": pdf.name, "filesize": pdf.stat().st_size, "mtime": int(pdf.stat().st_mtime * 1000)}).encode()
        condition = {'If-Match': previous_md5} if previous_md5 else {'If-None-Match': '*'}
        headers = {"Content-Type": "application/x-www-form-urlencoded", **condition}
        response, _ = self.call("POST", f"/users/0/items/{attachment_key}/file", data, headers=headers)
        if response.get("exists"):
            return False
        upload_url = response["url"]
        if urlparse(upload_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise PaperError("Local Zotero upload URL is not loopback; refused")
        # A remote Zotero returns its own loopback port, not our SSH forwarded port.
        upload_parts = urlparse(upload_url)
        base_parts = urlparse(self.base)
        upload_url = urlunparse(upload_parts._replace(scheme=base_parts.scheme, netloc=base_parts.netloc))
        body = response.get("prefix", "").encode() + pdf.read_bytes() + response.get("suffix", "").encode()
        status, _h, _b, _url = request_bytes("POST", upload_url, payload=body, headers={"Content-Type": response.get("contentType", "application/octet-stream")})
        if status != 201:
            raise PaperError(f"Local Zotero file upload failed: HTTP {status}")
        self.call("POST", f"/users/0/items/{attachment_key}/file", urlencode({"upload": response["uploadKey"]}).encode(), headers=headers)
        return True


def attachment_health(zotero, item_key: str, paper=None) -> dict:
    """Read-only: does the item have one PDF attachment whose file really exists?

    `has_pdf` only reads attachment metadata. An attachment can survive while its
    stored file is gone, so the file itself is resolved through Zotero's
    `file/view/url` endpoint and checked on disk.
    """
    pdf_children = [x for x in zotero.children(item_key)
                    if x.get("itemType") == "attachment"
                    and (x.get("contentType") == "application/pdf"
                         or str(x.get("filename", "")).lower().endswith(".pdf"))]
    files = []
    for child in pdf_children:
        entry = {"attachment_key": child.get("key"), "filename": child.get("filename", ""),
                 "linkMode": child.get('linkMode'), 'md5': child.get('md5'),
                 "file": None, "exists": False, 'verified': False,
                 'missing': False, 'state': 'UNVERIFIED'}
        try:
            uri = request_bytes("GET", zotero.base + f"/users/0/items/{child['key']}/file/view/url",
                                headers={'Zotero-Server-ID': zotero.server_id},
                                timeout=8)[2].decode().strip()
            if urlparse(uri).scheme != 'file' or urlparse(uri).netloc not in {'', 'localhost'}:
                raise PaperError('Unexpected attachment file URL')
            path = Path(url2pathname(urlparse(uri).path))
            entry["file"] = str(path)
            entry["exists"] = path.is_file() and path.stat().st_size > 0
            if entry['exists']:
                if paper:
                    valid, why = verify_pdf(path, paper)
                else:
                    try:
                        from pypdf import PdfReader
                        valid, why = bool(PdfReader(str(path), strict=False).pages), 'PDF readability checked'
                    except Exception as error:
                        valid, why = False, 'Unreadable PDF: '+str(error)
                entry.update(verified=valid, state='OK' if valid else 'INVALID_FILE', reason=why)
        except PaperError as error:
            # 404 is evidence from Zotero; a remote file path missing on *our*
            # filesystem is not. Network/auth failures must never trigger repair.
            if 'HTTP 404 ' in str(error):
                entry.update(missing=True, state='MISSING_FILE')
            else:
                entry['reason'] = str(error)
        except (OSError, ValueError, ImportError) as error:
            entry['reason'] = str(error)
        files.append(entry)
    if not files:
        state = "NO_ATTACHMENT"
    elif all(x['missing'] for x in files):
        state = "MISSING_FILE"
    elif not any(x['verified'] for x in files):
        state = 'INVALID_FILE' if any(x['state'] == 'INVALID_FILE' for x in files) else 'UNVERIFIED'
    elif len(files) > 1:
        state = "DUPLICATE"
    else:
        state = "OK"
    return {"state": state, "pdf_attachments": files}


def choose_collection(zotero: ZoteroLocal, paper: dict, specified: str | None) -> tuple[dict | None, list[dict]]:
    cols = zotero.collections()
    if not cols:
        raise PaperError("No existing Zotero Collections found")
    if specified:
        matching = [x for x in cols if x["path"] == specified] or [x for x in cols if x["name"] == specified]
        if len(matching) != 1:
            raise PaperError(f"Collection name/path missing or ambiguous: {specified}; run --list-collections")
        return matching[0], []
    query = tokens(paper["title"])
    ranked = []
    for col in cols:
        name_tokens = tokens(col["path"])
        name_score = len(query & name_tokens) / max(1, len(query))
        item_titles = [x.get("title", "") for x in zotero.collection_items(col["key"])]
        exemplar_score = max((len(query & tokens(title)) / max(1, len(query)) for title in item_titles), default=0)
        score = round(max(name_score, exemplar_score), 3)
        ranked.append({**col, "score": score, "example_count": len(item_titles)})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    best = ranked[0]
    runner = ranked[1]["score"] if len(ranked) > 1 else 0
    # A conservative lexical pilot. Ambiguous/new collections require an explicit choice.
    return (best if best["score"] >= 0.35 and best["score"] - runner >= 0.15 else None), ranked[:5]


def process(reference: str, args, zotero=None) -> dict:
    result = {"input": reference, "status": "PENDING", "pdf": None, "zotero": "not_modified", "warnings": []}
    try:
        record, confidence = crossref_metadata(reference, demo=args.demo)
        paper = paper_from_crossref(record)
        result.update({"paper": paper, "match_confidence": confidence})
        if not paper["doi"] or not paper["title"]:
            raise PaperError("Crossref metadata lacks DOI or title")
    except (PaperError, KeyError, IndexError, TypeError) as error:
        result.update({"status": "MATCH_REVIEW", "warnings": [str(error)]})
        return result

    chosen = None
    if zotero:
        try:
            chosen, ranked = choose_collection(zotero, paper, args.collection)
            result["collection_candidates"] = ranked
            if chosen:
                result["collection"] = chosen["path"]
            else:
                result["warnings"].append("No confident existing Collection match; specify --collection with an exact path")
        except PaperError as error:
            result["warnings"].append(str(error))
    else:
        result["warnings"].append("Zotero not connected: metadata/PDF discovery only")

    candidates = pdf_candidates(paper["doi"], demo=args.demo, errors=result["warnings"])
    if getattr(args, "institutional", False):
        for link in record.get("link") or []:
            url = link.get("URL", "")
            pii = re.search(r"api\.elsevier\.com/content/article/PII:([A-Z0-9]+)", url)
            if pii:
                candidate = {"url": "https://www.sciencedirect.com/science/article/pii/" + pii.group(1) + "/pdfft?isDTMRedir=true&download=true",
                             "source": "institutional_publisher", "version": "publishedVersion"}
                if candidate not in candidates:
                    candidates.append(candidate)
            elif link.get("content-type") == "application/pdf" and safe_pdf_url(url):
                candidates.append({"url": url, "source": "institutional_publisher", "version": "unknown"})
    candidates.extend({"url": url, "source": "explicit_pdf_url", "version": "unknown"} for url in PDF_URLS)
    result["pdf_candidates"] = candidates
    if args.apply:
        existing_key = None
        already_has_pdf = False
        if zotero and chosen:
            try:
                current = next((x for x in zotero.items() if x.get("DOI", "").lower() == paper["doi"]), None)
                if current:
                    existing_key = current["key"]
                    already_has_pdf = any(x.get('verified') for x in
                                          attachment_health(zotero, existing_key, paper)['pdf_attachments'])
            except PaperError as error:
                result["warnings"].append("Could not check existing attachments: " + str(error))
        if already_has_pdf:
            file, location, errors = None, None, []
            result["warnings"].append("Existing Zotero entry already has a PDF; skipped download")
        else:
            file, location, errors = download_verified(paper, candidates, Path(args.out))
        result["warnings"].extend(errors)
        attachment_result = None
        if file:
            result["pdf"] = str(file.resolve())
            result["pdf_location"] = location
            result['sha256'] = pdf_sha256(file)
        if zotero and chosen:
            try:
                key, created = zotero.ensure_item(paper, chosen["key"])
                result["zotero"] = "created" if created else "reused"
                result["zotero_key"] = key
                if file:
                    attachment_result = zotero.ensure_pdf(key, file, paper)
                    result.update(attachment_result)
            except PaperError as error:
                result["warnings"].append("Zotero write failed: " + str(error))
        result["status"] = (attachment_result['status'] if attachment_result else
                            ("PDF_ALREADY_PRESENT" if already_has_pdf else ("PDF_SAVED" if file else "PDF_PENDING")))
    else:
        result["status"] = "PREVIEW" if chosen or args.demo else "COLLECTION_REVIEW"
    return result


SAMPLE_REF = "Yinghua Liu, Zuhua Xu, Zhongxiang Ge, Jun Zhao, Wei Yan, Zhijiang Shao. Long-term demand prediction based on dual-stream guided diffusion model integrating production plans for oxygen supply network. Information Sciences, 755:123800, 2026."
SAMPLE_RECORD = {
    "DOI": "10.1016/j.ins.2026.123800",
    "title": ["Long-term demand prediction based on dual-stream guided diffusion model integrating production plans for oxygen supply network"],
    "author": [{"given": first, "family": last} for first, last in [("Yinghua", "Liu"), ("Zuhua", "Xu"), ("Zhongxiang", "Ge"), ("Jun", "Zhao"), ("Wei", "Yan"), ("Zhijiang", "Shao")]],
    "container-title": ["Information Sciences"], "volume": "755", "article-number": "123800",
    "published": {"date-parts": [[2026, 11, 5]]},
    "URL": "https://doi.org/10.1016/j.ins.2026.123800",
}


def main(argv=None):
    global PDF_PROXY, PDF_URLS, PDF_RATE_KIB, PDF_INTERVAL
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ref", help="One raw bibliographic reference, with or without DOI")
    source.add_argument("--input", help="UTF-8 text file, one reference per line")
    parser.add_argument("--collection", help="Exact existing Zotero collection name or full hierarchical path")
    parser.add_argument("--list-collections", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Download PDFs and write to Zotero; without this, no writes")
    parser.add_argument("--demo", action="store_true", help="Offline metadata example; no network lookup or OA candidates")
    parser.add_argument("--out", default="paper_downloads", help="PDF and JSON report folder")
    parser.add_argument("--no-zotero", action="store_true", help="Skip local Zotero reads/writes")
    parser.add_argument("--zotero-base", default=BASE, help="Loopback API address, including an SSH forwarded port")
    parser.add_argument("--pdf-proxy", help="HTTP proxy for PDF downloads, e.g. the zju-connect HTTP listener; default direct")
    parser.add_argument("--institutional", action="store_true", help="Try publisher PDF links using existing campus/authorized proxy access")
    parser.add_argument("--pdf-rate-kib", type=float, default=0, help="PDF download rate in KiB/s; 0 means unlimited (default)")
    parser.add_argument("--download-interval", type=float, default=30, help="Seconds between PDF attempts (default 30)")
    parser.add_argument("--pdf-url", action="append", default=[], help="Known authorized PDF URL; only for a single reference")
    args = parser.parse_args(argv)
    PDF_PROXY = args.pdf_proxy
    PDF_URLS = args.pdf_url
    if args.pdf_rate_kib < 0 or args.download_interval < 0:
        parser.error("PDF rate and interval must be nonnegative")
    PDF_RATE_KIB, PDF_INTERVAL = args.pdf_rate_kib, args.download_interval
    base = urlparse(args.zotero_base)
    if base.scheme != "http" or base.hostname not in {"localhost", "127.0.0.1", "::1"} or base.username or base.password:
        parser.error("--zotero-base must use a loopback HTTP endpoint; use SSH forwarding for another computer")
    if PDF_PROXY and (urlparse(PDF_PROXY).scheme not in {"http", "https"} or not urlparse(PDF_PROXY).hostname):
        parser.error("--pdf-proxy requires an HTTP(S) proxy URL")
    if not (args.ref or args.input or args.demo or args.list_collections):
        parser.error("Provide --ref, --input, --demo or --list-collections")
    if args.demo and args.apply:
        parser.error("--demo is deliberately read-only")
    refs = [args.ref] if args.ref else (Path(args.input).read_text(encoding="utf-8-sig").splitlines() if args.input else [SAMPLE_REF])
    refs = [x.strip() for x in refs if x and x.strip()]
    if PDF_URLS and len(refs) != 1:
        parser.error("--pdf-url requires exactly one reference")
    zotero = None
    if not args.no_zotero:
        try:
            zotero = ZoteroLocal(args.zotero_base)
        except PaperError as error:
            print(f"Zotero unavailable: {error}", file=sys.stderr)
            if args.apply:
                print("PDFs can still be downloaded, but Zotero will not be modified.", file=sys.stderr)
    if args.list_collections:
        if zotero is None:
            return 2
        for col in zotero.collections():
            print(col["path"])
        return 0
    results = []
    for idx, ref in enumerate(refs, start=1):
        result = process(ref, args, zotero)
        print(f"[{idx}/{len(refs)}] {result.get('status')} | {result.get('paper', {}).get('doi', ref[:55])} | {result.get('collection', 'no collection selected')}")
        results.append(result)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "report.json"
    report.write_text(json.dumps({"mode": "APPLY" if args.apply else "PREVIEW", "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {report.resolve()}")
    return 0 if all(x["status"] not in {"MATCH_REVIEW", "COLLECTION_REVIEW"} for x in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
