from src.ingestion.normalization import normalize_text, remove_repeated_page_furniture


def test_repeated_edge_furniture_is_removed_but_body_content_is_retained() -> None:
    pages = [
        ["DISTRICT PROCUREMENT", "Solicitation 100 | Page 1 of 3", "Instructions", "Product requirement applies", "Delivery terms", "Confidential"],
        ["District  Procurement", "Solicitation 100 | Page 2 of 3", "Instructions", "Product requirement applies", "Delivery terms", "Confidential"],
        ["district procurement", "Solicitation 100 | Page 3 of 3", "Instructions", "Product requirement applies", "Delivery terms", "Confidential"],
    ]

    cleaned_pages, removed_pages, uncertain_pages = remove_repeated_page_furniture(pages)

    assert cleaned_pages == [
        ["Instructions", "Product requirement applies", "Delivery terms"],
        ["Instructions", "Product requirement applies", "Delivery terms"],
        ["Instructions", "Product requirement applies", "Delivery terms"],
    ]
    assert all(len(removed) == 3 for removed in removed_pages)
    assert all(not uncertain for uncertain in uncertain_pages)


def test_infrequent_edge_line_is_preserved() -> None:
    pages = [
        ["Solicitation title", "Unique notice", "Body one", "Footer"],
        ["Solicitation title", "Different notice", "Body two", "Footer"],
        ["Different office", "Other notice", "Body three", "Footer"],
        ["Fourth office", "Fourth notice", "Body four", "Footer"],
        ["Fifth office", "Fifth notice", "Body five", "Footer"],
    ]

    cleaned_pages, _, uncertain_pages = remove_repeated_page_furniture(pages)

    assert "Unique notice" in cleaned_pages[0]
    assert "Different notice" in cleaned_pages[1]
    assert "Solicitation title" in cleaned_pages[0]
    assert "Solicitation title" in cleaned_pages[1]
    assert all("Solicitation title" in uncertain for uncertain in uncertain_pages[:2])


def test_substantive_repeated_header_word_is_not_layout_noise() -> None:
    text = "The header configuration is specified below\n" * 3

    assert normalize_text(text).count("The header configuration is specified below") == 3