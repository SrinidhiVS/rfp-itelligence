from __future__ import annotations

import json
from pathlib import Path

import pymupdf


FIXTURE_DIR = Path(__file__).parent


def create_unseen_bid_folder(root: Path) -> tuple[dict, Path]:
    descriptor = json.loads((FIXTURE_DIR / "unseen_bid.json").read_text(encoding="utf-8"))
    bid_folder = root / descriptor["bid_id"]
    notice_path = bid_folder / descriptor["notice_path"]
    pdf_path = bid_folder / descriptor["specification_path"]
    notice_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    notice_source = (FIXTURE_DIR / descriptor["notice_source"]).read_text(encoding="utf-8")
    notice_path.write_text(notice_source, encoding="utf-8")

    document = pymupdf.open()
    for page_lines in descriptor["pdf_pages"]:
        page = document.new_page()
        for line_index, line in enumerate(page_lines):
            page.insert_text((72, 72 + line_index * 28), line)
    document.save(pdf_path)
    document.close()
    return descriptor, bid_folder
