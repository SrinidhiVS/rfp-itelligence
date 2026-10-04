from src.extraction.citations import citation_from_evidence


def test_citation_preserves_pdf_page_and_locator():
    citation = citation_from_evidence({"record": {"source_file": "rfp.pdf", "page_number": 4, "source_locator": {"section": "deadline"}, "bid_id": "Bid1", "text": "deadline"}}, "Bid1")
    assert citation.page == 4
    assert citation.location["section"] == "deadline"


def test_citation_supports_html_location_without_page():
    citation = citation_from_evidence({"record": {"source_file": "bid.html", "source_locator": "submission", "bid_id": "Bid1", "text": "portal"}}, "Bid1")
    assert citation.page is None
    assert citation.location == "submission"
