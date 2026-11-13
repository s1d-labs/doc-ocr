# doc-ocr

This family reads scanned public documents with OCR on GitHub runners.

- Input: queue items with a signed link and a name.
- Output: `text/<name>.txt.gz` in the bucket, with a form feed between pages, and one record per document.
- A page with a usable text layer keeps that text. Other pages go through tesseract (English).

## Task `awards` (project doc-ocr-gepnic-awards)

- Input: one queue item for each GePNIC tender. The item names the GePNIC project, the tender ID and the stored price documents
  (bucket key and byte range). The task gets a short-lived link from the hub when it claims the item.
- The task reads the BOQ comparative chart (xlsx or xls) first, then the financial evaluation summary (pdf).
  A pdf without a text layer goes through tesseract (first 3 pages) only when the item has `"ocr": true` (pilot: 0 of 29 gave an L1).
- Rules only (`award_parse.py`): the "Bid Rank" summary table and the line "Lowest Amount Quoted BY". No AI.
- A result is kept only when the document names an L1 bidder with an amount, and its tender ID (if any) is the same as the item's.
- Output: one record per tender: L1 bidder, L1 amount, all bidders with amounts and ranks, document date, source document, method.
- L1 is the lowest quoted bid. It is not always the bidder that got the award.
- Tests: `python -m pytest tests`.
