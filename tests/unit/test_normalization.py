from src.ingestion.normalization import normalize_text


def test_normalization_repairs_layout_without_dropping_content() -> None:
    raw = "Header\nHeader\nHeader\nprocure-\nment   deadline\nFooter\nFooter\nFooter"
    normalized = normalize_text(raw)
    assert "procurement deadline" in normalized
    assert "Header" not in normalized
    assert "Footer" not in normalized


def test_normalization_keeps_repeated_substantive_text() -> None:
    normalized = normalize_text("Product requirement\nProduct requirement\nProduct requirement")
    assert normalized.count("Product requirement") == 3


def test_normalization_joins_wrapped_prose_and_dehyphenates_split_words() -> None:
    normalized = normalize_text("The selected vendor shall provide\nthree years of procure-\nment support.")

    assert normalized == "The selected vendor shall provide three years of procurement support."


def test_normalization_preserves_list_items_and_table_rows() -> None:
    raw = "Selected configuration:\n- 16 GB RAM\n- 512 GB SSD\nCPU | Core count\nGPU | Memory"

    assert normalize_text(raw) == raw
