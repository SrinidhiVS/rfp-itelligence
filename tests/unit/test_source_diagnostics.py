from src.extraction.source_diagnostics import diagnostic_for_source


def test_source_failure_is_recoverable_by_default():
    diagnostic = diagnostic_for_source("broken.pdf", "unreadable page")
    assert diagnostic.recoverable is True
    assert diagnostic.source_file == "broken.pdf"
