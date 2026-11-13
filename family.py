"""What this family does: it reads scanned public documents with OCR. Each project takes a list of signed links, seeded from the box that holds the keys."""
import json
from pathlib import Path

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]
PROJECTS = [{"name": f"{FAMILY}-dda-papers", "title": "DDA Authority and Technical Committee papers", "task": "ocr", "unit_label": "document", "record_label": "document read"},
            {"name": f"{FAMILY}-city", "title": "Tender documents of the city ledgers", "task": "ocr", "unit_label": "document", "record_label": "document read"},
            {"name": f"{FAMILY}-gepnic-awards", "title": "L1 bidder and quoted amounts from stored GePNIC price documents", "task": "awards",
             "unit_label": "tender", "record_label": "tender read", "max_workers": 20}]
