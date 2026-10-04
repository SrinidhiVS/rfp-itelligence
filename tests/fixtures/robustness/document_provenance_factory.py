from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf


FIXTURE_DIR = Path(__file__).parent


def create_robustness_document_folder(root: Path) -> Path:
    bid_folder = root / "RobustDocs"
    table_path = bid_folder / "procurement" / "table-document.html"
    pdf_path = bid_folder / "technical" / "long-document.pdf"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_DIR / "table-document.html", table_path)

    document = pymupdf.open()
    for page_number in (1, 2):
        page = document.new_page()
        words = [f"LONG_PAGE_{page_number}_START"]
        words.extend(f"page{page_number}word{index}" for index in range(170))
        words.append(f"LONG_PAGE_{page_number}_END")
        page.insert_textbox(
            pymupdf.Rect(48, 48, 548, 790),
            " ".join(words),
            fontsize=10,
        )
    document.save(pdf_path)
    document.close()
    return bid_folder
