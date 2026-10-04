from src.ingestion.chunking import make_chunks
from src.ingestion.models import DocumentSection, ExtractedTable, NormalizedPage, SourceDocument


def _section(section_id, kind, text, heading_path, **kwargs):
    return DocumentSection(
        section_id=section_id,
        kind=kind,
        text=text,
        heading_level=kwargs.get("heading_level"),
        heading_path=heading_path,
        page_id=kwargs.get("page_id", "page-1"),
        table_id=kwargs.get("table_id"),
        source_locator={"page_number": kwargs.get("page_number", 1), "section_id": section_id},
    )


def _document(sections, tables=None, normalized_text=""):
    page = NormalizedPage(
        page_id="page-1",
        document_id="doc-1",
        page_number=1,
        section_title="Overview",
        raw_text=normalized_text,
        normalized_text=normalized_text,
        tables=tables or [],
        sections=sections,
    )
    return SourceDocument(
        document_id="doc-1",
        bid_id="Bid1",
        file_name="spec.pdf",
        relative_path="documents/spec.pdf",
        detected_format="pdf",
        doc_type="specs",
        addendum_number=None,
        document_date=None,
        status="parsed",
        pages=[page],
    )


def test_long_section_splits_at_limit_with_same_section_overlap():
    words = [f"word{index}" for index in range(170)]
    section = _section("s1", "paragraph", " ".join(words), ["Requirements"])

    chunks = make_chunks(_document([section]), "Bid1")

    assert len(chunks) == 2
    assert all(len(chunk.text.split()) <= 150 for chunk in chunks)
    assert chunks[0].text.split()[-20:] == chunks[1].text.split()[:20]
    assert [chunk.section_title for chunk in chunks] == ["Requirements", "Requirements"]
    assert chunks[0].text.split()[0] == "word0"
    assert chunks[1].text.split()[-1] == "word169"


def test_heading_boundaries_do_not_merge_or_overlap_sections():
    first = _section("s1", "paragraph", " ".join(f"alpha{i}" for i in range(80)), ["Eligibility"])
    second = _section("s2", "paragraph", " ".join(f"beta{i}" for i in range(80)), ["Submission"])

    chunks = make_chunks(_document([first, second]), "Bid1")

    assert [chunk.section_title for chunk in chunks] == ["Eligibility", "Submission"]
    assert chunks[0].text.split()[-20:] != chunks[1].text.split()[:20]
    assert chunks[0].source_locator["section_title"] == "Eligibility"
    assert chunks[1].source_locator["section_title"] == "Submission"


def test_tables_remain_distinct_and_ids_are_deterministic():
    table = ExtractedTable(
        table_id="table-1",
        page_id="page-1",
        title="Pricing",
        columns=["Item", "Cost"],
        rows=[["Laptop", "$500"]],
    )
    sections = [
        _section("s1", "paragraph", "Prose before table.", ["Pricing"]),
        _section("s2", "table", "Laptop $500", ["Pricing"], table_id="table-1"),
        _section("s3", "paragraph", "Prose after table.", ["Pricing"]),
    ]
    document = _document(sections, [table])

    chunks = make_chunks(document, "Bid1")
    repeated = make_chunks(document, "Bid1")

    assert [chunk.content_kind for chunk in chunks].count("table") == 1
    table_chunk = next(chunk for chunk in chunks if chunk.content_kind == "table")
    assert table_chunk.source_locator["table_id"] == "table-1"
    assert "Laptop" in table_chunk.text and "Cost" in table_chunk.text
    assert all("Laptop" not in chunk.text for chunk in chunks if chunk.content_kind == "text")
    assert [chunk.chunk_id for chunk in chunks] == [chunk.chunk_id for chunk in repeated]


def test_short_section_is_not_duplicated_by_overlap():
    section = _section("s1", "paragraph", "Only eight short words belong in this section today.", ["Notes"])

    chunks = make_chunks(_document([section]), "Bid1")

    assert len(chunks) == 1
    assert chunks[0].text == section.text


def test_same_section_continuation_overlaps_across_pages_with_all_page_provenance():
    first_section = _section(
        "page-1-section-1", "paragraph", " ".join(f"first{index}" for index in range(100)),
        ["Requirements"], page_id="page-1", page_number=1,
    )
    second_section = _section(
        "page-2-section-1", "paragraph", " ".join(f"second{index}" for index in range(100)),
        ["Requirements"], page_id="page-2", page_number=2,
    )
    first_page = NormalizedPage("page-1", "doc-1", 1, "Requirements", None, first_section.text, sections=[first_section])
    second_page = NormalizedPage("page-2", "doc-1", 2, "Requirements", None, second_section.text, sections=[second_section])
    document = SourceDocument(
        "doc-1", "Bid1", "spec.pdf", "documents/spec.pdf", "pdf", "specs", None, None,
        "parsed", pages=[first_page, second_page],
    )

    chunks = make_chunks(document, "Bid1")

    assert len(chunks) == 2
    assert chunks[0].text.split()[-20:] == chunks[1].text.split()[:20]
    assert chunks[1].source_locator["page_numbers"] == [1, 2]
    assert [item["section_id"] for item in chunks[1].source_locator["source_segments"]] == [
        "page-1-section-1", "page-2-section-1",
    ]


def test_long_section_prefers_sentence_boundaries_and_keeps_overlap():
    sentences = []
    for sentence_index in range(6):
        words = [f"s{sentence_index}w{word_index}" for word_index in range(29)]
        words.append(f"s{sentence_index}w29.")
        sentences.append(" ".join(words))
    section = _section("s1", "paragraph", " ".join(sentences), ["Requirements"])

    chunks = make_chunks(_document([section]), "Bid1")

    assert len(chunks[0].text.split()) == 120
    assert chunks[0].text.split()[-1].endswith(".")
    assert chunks[0].text.split()[-20:] == chunks[1].text.split()[:20]


def test_long_section_prefers_paragraph_boundaries_and_keeps_overlap():
    first_paragraph = " ".join(f"first{index}" for index in range(90))
    second_paragraph = " ".join(f"second{index}" for index in range(160))
    section = _section("s1", "paragraph", f"{first_paragraph}\n{second_paragraph}", ["Requirements"])

    chunks = make_chunks(_document([section]), "Bid1")

    assert chunks[0].text.split()[-1] == "first89"
    assert chunks[0].text.split()[-20:] == chunks[1].text.split()[:20]
    assert all(len(chunk.text.split()) <= 150 for chunk in chunks)


def test_long_two_page_section_keeps_boundary_text_overlap_and_page_provenance():
    first_text = " ".join(["LONG_PAGE_1_START", *(f"first{index}" for index in range(170)), "LONG_PAGE_1_END"])
    second_text = " ".join(["LONG_PAGE_2_START", *(f"second{index}" for index in range(170)), "LONG_PAGE_2_END"])
    first_section = _section(
        "long-page-1", "paragraph", first_text, ["Specifications"], page_id="long-page-1", page_number=1
    )
    second_section = _section(
        "long-page-2", "paragraph", second_text, ["Specifications"], page_id="long-page-2", page_number=2
    )
    pages = [
        NormalizedPage("long-page-1", "long-document", 1, "Specifications", first_text, first_text, sections=[first_section]),
        NormalizedPage("long-page-2", "long-document", 2, "Specifications", second_text, second_text, sections=[second_section]),
    ]
    document = SourceDocument(
        "long-document", "RobustDocs", "long-document.pdf", "technical/long-document.pdf", "pdf",
        "specs", None, None, "parsed", pages=pages,
    )

    chunks = make_chunks(document, "RobustDocs")
    combined_text = " ".join(chunk.text for chunk in chunks)

    assert len(chunks) >= 3
    assert all(len(chunk.text.split()) <= 150 for chunk in chunks)
    assert chunks[0].text.split()[-20:] == chunks[1].text.split()[:20]
    assert all(marker in combined_text for marker in (
        "LONG_PAGE_1_START", "LONG_PAGE_1_END", "LONG_PAGE_2_START", "LONG_PAGE_2_END"
    ))
    assert any(chunk.source_locator["page_numbers"] == [1, 2] for chunk in chunks)
    assert {page_number for chunk in chunks for page_number in chunk.source_locator["page_numbers"]} == {1, 2}