import json
from types import SimpleNamespace

from src.extraction.cli import main
from src.extraction.fields import CANONICAL_FIELDS


def test_cli_extract_writes_one_record(tmp_path, monkeypatch):
    class EmptyStore:
        records = []

    monkeypatch.setattr("src.extraction.cli.CorpusStore", lambda _path: type("Store", (), {"load": lambda self: EmptyStore()})())
    assert main(["extract", "--input", "Unseen Bid", "--output", str(tmp_path)]) == 0
    records = list(tmp_path.glob("*/structured-record.json"))
    assert len(records) == 1
    assert records[0].parent.name.isdigit()
    assert len(records[0].parent.name) == 12


def test_cli_serializes_collection_items_and_all_canonical_fields(tmp_path, monkeypatch):
    record = SimpleNamespace(
        record_id="product-1",
        source_file="products.pdf",
        page_number=1,
        source_locator={"row": 1},
        bid_id="Bid1",
        doc_type="rfp",
        addendum_number=None,
        document_date=None,
        text="Product: Laptop Alpha; quantity: 10; model number: ZX100.",
        status="current",
    )
    class ProductCorpus:
        records = [record]

    monkeypatch.setattr("src.extraction.cli.CorpusStore", lambda _path: type("Store", (), {"load": lambda self: ProductCorpus()})())

    assert main(["extract", "--input", "Bid1", "--output", str(tmp_path)]) == 0
    record_path = next(tmp_path.glob("*/structured-record.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert set(CANONICAL_FIELDS) == set(record["fields"])
    product = record["fields"]["Product"]
    assert isinstance(product["value"], list)
    assert product["value"][0]["value"] == "Laptop Alpha"
    assert product["value"][0]["citations"][0]["file"] == "products.pdf"


def test_cli_extracts_from_all_matching_indexed_records(tmp_path, monkeypatch):
    records = [
        SimpleNamespace(
            record_id=f"document-{index}",
            source_file=f"documents-{index}.pdf",
            page_number=index + 1,
            source_locator={"page": index + 1},
            bid_id="Bid1",
            doc_type="rfp",
            addendum_number=None,
            document_date=None,
            text=f"Required documents: Affidavit Form {index:02d}.",
            status="current",
        )
        for index in range(15)
    ]

    monkeypatch.setattr("src.extraction.cli.CorpusStore", lambda _path: type("Store", (), {"load": lambda self: type("Corpus", (), {"records": records})()})())

    assert main(["extract", "--input", "Bid1", "--output", str(tmp_path)]) == 0
    record_path = next(tmp_path.glob("*/structured-record.json"))
    output = json.loads(record_path.read_text(encoding="utf-8"))

    documents = output["fields"]["Any Additional Documentation Required"]["value"]
    assert len(documents) == len(records)
