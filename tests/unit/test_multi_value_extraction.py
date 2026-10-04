from src.extraction.extractor import StructuredExtractor
from src.extraction.normalization import normalize_collection_items


def evidence(source, page, text):
    return {
        "record": {
            "source_file": source,
            "page_number": page,
            "source_locator": f"page {page}",
            "bid_id": "Bid1",
            "doc_type": "rfp",
            "text": text,
        }
    }


def test_required_documents_collect_distinct_items_across_sources():
    record = StructuredExtractor().extract("Bid1", [
        evidence("forms.pdf", 1, "Additional documents required: W-9, Vendor affidavit."),
        evidence("insurance.pdf", 2, "Required documents: vendor affidavit, Insurance certificate."),
    ])

    field = record.fields["Any Additional Documentation Required"]
    assert [item.value for item in field.value] == ["W-9", "Vendor affidavit", "Insurance certificate"]
    assert all(item.citations for item in field.value)
    assert {citation.file for item in field.value for citation in item.citations} == {"forms.pdf", "insurance.pdf"}


def test_product_items_keep_quantity_and_identifiers_associated():
    record = StructuredExtractor().extract("Bid1", [
        evidence("products.pdf", 1, "Product: Laptop Alpha; quantity: 10; model number: ZX100; part number: AB-10."),
        evidence("products.pdf", 2, "Product: Laptop Beta; quantity: 4; model number: ZX200; part number: AB-20."),
    ])

    products = record.fields["Product"].value
    assert [item.value for item in products] == ["Laptop Alpha", "Laptop Beta"]
    assert products[0].attributes == {"quantity": 10, "model_no": "ZX100", "part_no": "AB-10"}
    assert products[1].attributes == {"quantity": 4, "model_no": "ZX200", "part_no": "AB-20"}
    assert all(item.citations for item in products)
    assert [item.value for item in record.fields["Model_no"].value] == ["ZX100", "ZX200"]
    assert [item.value for item in record.fields["Part_no"].value] == ["AB-10", "AB-20"]


def test_scope_product_categories_are_all_returned():
    items = normalize_collection_items(
        "Product",
        "This RFP will be for computing devices, including laptops, desktops, tablet devices, and display monitors.",
    )

    assert [value for value, _ in items] == ["laptops", "desktops", "tablet devices", "display monitors"]


def test_sku_block_returns_every_part_number_before_product_description():
    text = "SKU\n210-BLYZ\n379-BFNZ\n619-ARSB\n658-BCSB\nSI# CC7802 Dell Latitude 5550\nDescription"

    items = normalize_collection_items("Part_no", text)

    assert [value for value, _ in items] == ["210-BLYZ", "379-BFNZ", "619-ARSB", "658-BCSB"]


def test_document_requirements_extract_all_items_from_explicit_list():
    items = normalize_collection_items(
        "Any Additional Documentation Required",
        "Required documents: Mercury Affidavit, Warranty certificate or affidavit.",
    )

    assert [value for value, _ in items] == ["Mercury Affidavit", "Warranty certificate or affidavit"]