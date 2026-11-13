"""Rules of award_parse.py on saved GePNIC price documents (public records)."""
from pathlib import Path

import pytest

from award_parse import check, parse_rows, parse_text, sheet_rows

F = Path(__file__).parent / "files"


@pytest.mark.parametrize("name,rid,l1,amount", [
    ("2013_PWDJK_9730_3.xls", "2013_PWDJK_9730_3", "RAVI KANT GUPTA", 868952.0),          # old xls chart, 9 bidders
    ("2021_PWDJK_133566_1.xlsx", "2021_PWDJK_133566_1", "SHARMA CONSTRUCTION", 150646.0),  # new xlsx chart with item lines
    ("2015_pwd_4025_3.xls", "2015_pwd_4025_3", "arya construction co", 39232847.41),       # amount in scientific notation
])
def test_boq_charts(name, rid, l1, amount):
    out = parse_rows(sheet_rows((F / name).read_bytes()))
    assert check(out, rid) == "ok"
    assert out["l1"] == l1 and abs(out["l1_amount"] - amount) < 1
    assert min(b["amount"] for b in out["bidders"]) == out["l1_amount"]


def test_chart_lists_every_bidder():
    out = parse_rows(sheet_rows((F / "2013_PWDJK_9730_3.xls").read_bytes()))
    assert len(out["bidders"]) == 9 and sorted(b["rank"] for b in out["bidders"]) == list(range(1, 10))
    assert out["doc_date"] == "06-Nov-2013"


def test_pdf_rank_table():
    out = parse_text((F / "2016_BBNDA_10449_1.txt").read_text())
    assert check(out, "2016_BBNDA_10449_1") == "ok" and out["l1"] == "GOPAL DASS" and out["l1_amount"] == 140306.5


def test_pdf_lowest_line():
    out = parse_text((F / "2018_UITUD_107525_1.txt").read_text())
    assert check(out, "2018_UITUD_107525_1") == "ok" and out["l1"] == "M/s Pradeep Soni" and out["l1_amount"] == 583742.14


def test_document_of_another_tender_is_refused():
    out = parse_text((F / "2017_UPPRD_65227_96.txt").read_text())
    assert check(out, "2017_UPPRD_65227_96") == "tender_id_mismatch"


def test_no_l1_in_free_text():
    assert check(parse_text("Two bids received and accepted.\nSignature Not Verified"), "2014_PWDJK_13335_1") == "no_l1"


def test_bid_id_suffix_is_removed():
    from award_parse import clean_name
    assert clean_name("MS SILAICH CONSTRUCTION CO (BID ID -3648867)") == "MS SILAICH CONSTRUCTION CO"
    assert clean_name("SHARMA CONSTRUCTION(GSTN-NA)") == "SHARMA CONSTRUCTION"
