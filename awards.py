#!/usr/bin/env python3
"""Pool task: read the L1 bidder and the quoted amounts of one GePNIC tender from its stored price documents.

A queue item names the GePNIC project (target), the tender (rid) and its stored documents (key, byte range, type), best first:
BOQ comparative charts (xlsx / xls), then financial evaluation summaries (pdf). The task asks the hub for a short-lived link at
claim time, reads each document by byte range, and stops at the first document that names the L1 bidder with an amount.
A pdf without a text layer goes through tesseract (first pages only). Rules only, no AI. One record per tender.
"""
import os
import subprocess
import sys
import tempfile
import time

import requests
from scrape_hub_client import HubClient

from award_parse import check, parse_rows, parse_text, sheet_rows

PROJECT = os.environ["SCRAPE_POOL_PROJECT"]
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
OCR_PAGES = 3
GOOD = 100      # letters in a pdf text layer below which the pdf is read with OCR


def letters(s):
    return sum(c.isascii() and c.isalpha() for c in s)


def pdf_text(data):
    with tempfile.TemporaryDirectory() as tmp:
        pdf = f"{tmp}/d.pdf"
        open(pdf, "wb").write(data)
        t = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, timeout=120).stdout.decode("utf8", "replace")
        if letters(t) >= GOOD:
            return t, False
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(OCR_PAGES), pdf, f"{tmp}/p"], capture_output=True, timeout=300)
        pages = []
        for f in sorted(x for x in os.listdir(tmp) if x.startswith("p") and x.endswith(".pgm")):
            o = subprocess.run(["tesseract", f"{tmp}/{f}", "-", "-l", "eng", "--psm", "6"], capture_output=True, timeout=240,
                               env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout.decode("utf8", "replace")
            pages.append(o)
        o = "\f".join(pages)
        return (o if letters(o) > letters(t) else t), True


def read_doc(hub, session, url, d):
    head = {"Range": f"bytes={d['range'][0]}-{d['range'][0] + d['range'][1] - 1}"} if d.get("range") else {}
    t = time.time()
    try:
        r = session.get(url, headers=head, timeout=(30, 300))
    except requests.RequestException:
        hub.metric("http_error"); hub.error()
        raise
    hub.metric("n_http"); hub.metric("t_http_s", time.time() - t)
    if r.status_code not in (200, 206):
        hub.metric(f"http_{r.status_code}")
        r.raise_for_status()
    return r.content


def one(hub, session, it):
    p = it["payload"]
    docs = p["docs"]
    urls = hub.read_urls(p["target"], sorted({d["key"] for d in docs}))
    tried = []
    for d in docs:
        data = read_doc(hub, session, urls[d["key"]], d)
        ocr = False
        if data[:4] == b"%PDF":
            text, ocr = pdf_text(data)
            out = parse_text(text)
        else:
            try:
                out = parse_rows(sheet_rows(data))
            except Exception as e:          # a damaged sheet: try the next document
                tried.append({"name": d.get("name"), "type": d.get("type"), "result": "unreadable", "error": repr(e)[:120]})
                continue
        if ocr:
            hub.metric("ocr_docs")
        verdict = check(out, p["rid"])
        tried.append({"name": d.get("name"), "type": d.get("type"), "result": verdict, "ocr": ocr})
        if verdict == "ok":
            return {"rid": p["rid"], "portal": p["target"], "status": "found", "l1": out["l1"], "l1_amount": out["l1_amount"],
                    "bidders": out.get("bidders", [])[:200], "tie": out.get("tie"), "doc_tender_id": out.get("tender_id"),
                    "doc_date": out.get("doc_date"), "how": out["how"], "ocr": ocr, "source_key": d["key"],
                    "source_range": d.get("range"), "source_name": d.get("name"), "source_type": d.get("type"), "tried": tried}
    return {"rid": p["rid"], "portal": p["target"], "status": "none", "tried": tried}


def main():
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    s = requests.Session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(5, steal=True, retry_failed=True)
            if not items:
                break
            for it in items:
                try:
                    rec = one(hub, s, it)
                    hub.record(it["key"], rec)
                    hub.metric("l1_found" if rec["status"] == "found" else "l1_none")
                    hub.complete([it["key"]], "done", fetched=1)
                except Exception as e:
                    print("failed", it["key"], repr(e)[:200], file=sys.stderr)
                    hub.complete([it["key"]], "failed", error=repr(e)[:200])
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    main()
