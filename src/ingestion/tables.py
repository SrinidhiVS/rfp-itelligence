"""Normalize extracted rows into rectangular, traceable table models."""

from __future__ import annotations

from collections.abc import Iterable

from .models import ExtractedTable, NormalizedPage
from .provenance import table_id
from .diagnostics import diagnostic


def table_from_rows(
    page_id: str,
    index: int,
    rows: Iterable[list[str | None]],
    title: str | None = None,
    source_bounds: dict | None = None,
    *,
    has_header: bool | None = True,
    header_names: list[str | None] | None = None,
) -> ExtractedTable:
    """Build a table with normalized header and equally sized data rows.

    Args:
        page_id: Owning normalized page identifier.
        index: Zero-based table index on that page.
        rows: Iterable of extracted row cell lists; cells may be ``None``.
        title: Optional table title/section name.
        source_bounds: Optional source-coordinate mapping, commonly PDF bounds.
        has_header: Whether the first row is a header; ``None`` means unknown.
        header_names: Optional externally detected header names, which take
            precedence over row-derived headers.

    Returns:
        ``ExtractedTable`` with padded rectangular rows and columns. Uneven
        input rows or headers mark status as partial and add a table_uncertain
        diagnostic.
    """
    materialized = [list(row) for row in rows]
    if header_names is not None:
        columns = list(header_names)
        data_rows = materialized
        has_header = True
    elif has_header is True:
        columns = materialized.pop(0) if materialized else []
        data_rows = materialized
    else:
        columns = []
        data_rows = materialized

    width = max([len(columns), *(len(row) for row in data_rows)], default=0)
    uneven_rows = any(len(row) != width for row in data_rows)
    uneven_header = has_header is True and header_names is None and bool(data_rows) and len(columns) != width
    columns = columns + [None] * (width - len(columns))
    if has_header is False or has_header is None:
        columns = [None] * width
    normalized_rows = [row + [None] * (width - len(row)) for row in data_rows]
    result = ExtractedTable(
        table_id(page_id, index), page_id, title, columns, normalized_rows,
        source_bounds=source_bounds, has_header=has_header,
    )
    if uneven_rows or uneven_header:
        result.status = "partial"
        result.diagnostics.append(diagnostic("table", "table_uncertain", "Rows have inconsistent cell counts", source_locator={"table_id": result.table_id}))
    return result


def attach_tables(page: NormalizedPage, tables: list[ExtractedTable]) -> None:
    """Append extracted tables to a normalized page in their given order.

    Args:
        page: Page receiving the tables.
        tables: Table models to append.

    Returns:
        ``None``; mutates ``page.tables``.
    """
    page.tables.extend(tables)
