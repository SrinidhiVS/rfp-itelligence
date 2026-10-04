from src.ingestion.tables import table_from_rows


def test_table_source_bounds_are_serializable() -> None:
    table = table_from_rows("page", 0, [["Field"], ["Value"]], source_bounds={"x0": 1, "y0": 2, "x1": 3, "y1": 4})
    assert table.source_bounds == {"x0": 1, "y0": 2, "x1": 3, "y1": 4}
