"""Rule-based reading of GePNIC price documents: the BOQ comparative chart (xlsx / xls) and the financial evaluation summary (pdf text).
Pure functions. Output: tender_id, bidders [{name, amount, rank, sheet}], l1, l1_amount, doc_date, how. No AI."""
import io
import re

MONEY = re.compile(r"^-?\d[\d,]*(\.\d*)?([eE][+-]?\d+)?$")
RANK = re.compile(r"^L\s*-?\s*(\d{1,3})$", re.I)
TID = re.compile(r"\b(20\d\d_[A-Za-z0-9&.-]+_\d+_\d+)\b")
DATE = re.compile(r"Created Date/Time\s*:?\s*(\d{1,2}-[A-Za-z]{3}-\d{4})")
LOWEST = re.compile(r"Lowest Amount Quoted\s*BY\s*:?\s*(.+?)\s*\(\s*([\d,]+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s*\)", re.I)
LOWEST_NOAMT = re.compile(r"Lowest Amount Quoted\s*BY\s*:?\s*([A-Za-z][^\n(]{2,120})", re.I)


def money(s):
    s = str(s).strip().replace(" ", "")
    if not MONEY.match(s):
        return None
    try:
        v = float(s.replace(",", "").rstrip("."))
    except ValueError:
        return None
    return v if v > 0 else None


def clean_name(s):
    s = re.sub(r"\(GSTN[^)]*\)", "", str(s))
    s = re.sub(r"\s+", " ", s).strip(" .,:-")
    return s


def _finish(out, bidders, how):
    out["bidders"] = bidders
    if not bidders:
        return out
    sheets = sorted({b.get("sheet") or "" for b in bidders})
    l1 = [b for b in bidders if b.get("rank") == 1]
    if len(sheets) > 1:
        # one total per bidder over the BOQ sheets, only for bidders priced in every sheet
        tot = {}
        for b in bidders:
            tot.setdefault(b["name"], {})[b.get("sheet") or ""] = b["amount"]
        full = {n: sum(v.values()) for n, v in tot.items() if len(v) == len(sheets) and all(x for x in v.values())}
        if full:
            n = min(full, key=full.get)
            out.update(l1=n, l1_amount=round(full[n], 2), how=how + "_multisheet")
        return out
    if len(l1) >= 1:
        out.update(l1=l1[0]["name"], l1_amount=l1[0]["amount"], how=how)
        if len(l1) > 1:
            out["tie"] = [b["name"] for b in l1]
    return out


def parse_rows(rows):
    """rows: list of lists of cell strings (all sheets in order)."""
    text = "\n".join("\t".join(r) for r in rows)
    out = {"tender_id": (TID.search(text) or [None, None])[1], "doc_date": (DATE.search(text) or [None, None])[1]}
    bidders, hdr = [], None
    for r in rows:
        low = [c.lower() for c in r]
        if any("bidder name" in c for c in low) and any(c.replace(" ", "") == "bidrank" for c in low):
            hdr = {"name": next(i for i, c in enumerate(low) if "bidder name" in c),
                   "amount": next((i for i, c in enumerate(low) if c.startswith("amount")), None),
                   "rank": next(i for i, c in enumerate(low) if c.replace(" ", "") == "bidrank"),
                   "sheet": next((i for i, c in enumerate(low) if c == "sheet name"), None)}
            last_sheet = ""
            continue
        if hdr is None:
            continue
        def cell(k):
            i = hdr.get(k)
            return r[i] if i is not None and i < len(r) else ""
        m = RANK.match(cell("rank").strip())
        amt = money(cell("amount"))
        name = clean_name(cell("name"))
        if not m or not name or amt is None:
            if not any(x.strip() for x in r):
                continue
            if bidders and not m:
                hdr = None          # end of the summary table
            continue
        sh = cell("sheet").strip() or last_sheet
        last_sheet = sh
        bidders.append({"name": name, "amount": amt, "rank": int(m.group(1)), "sheet": sh})
    out = _finish(out, bidders, "boq_chart_summary")
    if not out.get("l1"):
        lo = LOWEST.findall(text)
        if len(lo) == 1:
            out.update(l1=clean_name(lo[0][0]), l1_amount=money(lo[0][1]), how="boq_chart_lowest_line")
    return out


ROWLINE = re.compile(r"^\s*(?:(BoQ\d+)\s+)?(\d{1,3})(?:\.0)?\s+(.+?)\s{2,}([\d,]+(?:\.\d*)?)\s+L\s*-?\s*(\d{1,3})\b", re.I)


def parse_text(text):
    """Text of a pdf (pdftotext -layout or OCR). Reads the GePNIC summary table lines or the 'Lowest Amount Quoted BY' line."""
    out = {"tender_id": (TID.search(text) or [None, None])[1], "doc_date": (DATE.search(text) or [None, None])[1]}
    bidders, sheet = [], ""
    for line in text.splitlines():
        m = ROWLINE.match(line)
        if not m:
            continue
        amt = money(m.group(4))
        name = clean_name(m.group(3))
        if amt is None or not re.search(r"[A-Za-z]{2}", name):
            continue
        sheet = m.group(1) or sheet
        bidders.append({"name": name, "amount": amt, "rank": int(m.group(5)), "sheet": sheet})
    out = _finish(out, bidders, "fin_pdf_rank_table")
    if not out.get("l1"):
        lo = LOWEST.findall(text)
        if len(lo) == 1 and money(lo[0][1]):
            out.update(l1=clean_name(lo[0][0]), l1_amount=money(lo[0][1]), how="fin_pdf_lowest_line")
        elif not lo:
            m = LOWEST_NOAMT.search(text)
            if m:
                out.update(l1=clean_name(m.group(1)), l1_amount=None, how="fin_pdf_lowest_line_noamount")
    return out


def sheet_rows(data):
    """Cell rows (strings) of every sheet of an xlsx or xls file. openpyxl in full mode: read-only mode stops early on these files."""
    rows = []
    if data[:4] == b"PK\x03\x04":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                rows.append(["" if v is None else str(v).strip() for v in r])
    elif data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        for ws in wb.sheets():
            for i in range(ws.nrows):
                rows.append(["" if v in (None, "") else str(v).strip() for v in ws.row_values(i)])
    return rows


def check(out, rid):
    """Keep a result only when it names an L1 and, if the document names a tender ID, that ID is this work's ID."""
    if out.get("tender_id") and out["tender_id"].lower() != rid.lower():
        return "tender_id_mismatch"
    if not out.get("l1"):
        return "no_l1"
    if not out.get("l1_amount"):
        return "no_amount"
    return "ok"
