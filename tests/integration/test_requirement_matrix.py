from pathlib import Path


def test_requirement_matrix_document_exists_and_has_all_requirement_ranges():
    matrix = Path("docs/structured-extraction-validation.md").read_text(encoding="utf-8")
    assert "FR-001" in matrix and "FR-020" in matrix
    assert "SC-001" in matrix and "SC-012" in matrix
    assert "US1/AC1" in matrix and "US2/AC1" in matrix and "US3/AC1" in matrix
