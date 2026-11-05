#!/usr/bin/env python3
"""Pool task: read one scanned PDF with OCR. A queue item holds a signed link (url) and a name (name).

A page with a good text layer keeps that text. Other pages go through pdftoppm and tesseract.
Output: text/<name>.txt.gz in the bucket, with a form feed between pages, and one record per document.
"""
import concurrent.futures
import gzip
import hashlib
import os
import subprocess
import sys
import tempfile
import time

import requests
from scrape_hub_client import HubClient

PROJECT = os.environ["SCRAPE_POOL_PROJECT"]
DPI = "170"
GOOD = 300      # letters on a page with a usable text layer
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300


def letters(s):
    return sum(c.isascii() and c.isalpha() for c in s)


def page_text(pdf, n, tmp):
    t = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", pdf, "-"], capture_output=True, timeout=120).stdout.decode("utf8", "replace")
    if letters(t) >= GOOD:
        return t, 0
    base = f"{tmp}/p{n}"
    subprocess.run(["pdftoppm", "-r", DPI, "-gray", "-f", str(n), "-l", str(n), "-singlefile", pdf, base], capture_output=True, timeout=180)
    if not os.path.exists(base + ".pgm"):
        return t, 0
    o = subprocess.run(["tesseract", base + ".pgm", "-", "-l", "eng", "--psm", "4"], capture_output=True, timeout=240,
                       env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout.decode("utf8", "replace")
    os.remove(base + ".pgm")
    return (o if letters(o) > letters(t) else t), 1


def read(pdf):
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=60).stdout
    pages = next((int(x.split()[-1]) for x in info.splitlines() if x.startswith("Pages:")), 0)
    with tempfile.TemporaryDirectory() as tmp, concurrent.futures.ThreadPoolExecutor(2) as ex:
        out = list(ex.map(lambda n: page_text(pdf, n, tmp), range(1, pages + 1)))
    return "\f".join(x[0] for x in out), pages, sum(x[1] for x in out)


def main():
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    while time.time() < DEADLINE:
        items = hub.claim(1, steal=True, retry_failed=True)
        if not items:
            break
        it = items[0]
        p = it["payload"]
        start = time.time()
        try:
            r = requests.get(p["url"], timeout=(30, 600))
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(r.content)
                f.flush()
                text, pages, scanned = read(f.name)
            path = f"text/{p['name']}.txt.gz"
            hub.upload_many([(path, gzip.compress(text.encode("utf8")), "application/gzip")])
            hub.record(it["key"], {"name": p["name"], "pages": pages, "scanned": scanned, "chars": len(text), "file": path, "seconds": round(time.time() - start),
                                   "sha1": hashlib.sha1(r.content).hexdigest()})
            hub.complete([it["key"]], "done", fetched=1)
        except Exception as e:
            print("failed", it["key"], repr(e)[:200], file=sys.stderr)
            hub.complete([it["key"]], "failed", error=repr(e)[:200])
    hub.close("finished", "")


main()
