# doc-ocr

This family reads scanned public documents with OCR on GitHub runners.

- Input: queue items with a signed link and a name.
- Output: `text/<name>.txt.gz` in the bucket, with a form feed between pages, and one record per document.
- A page with a usable text layer keeps that text. Other pages go through tesseract (English).
