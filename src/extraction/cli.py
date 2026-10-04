"""Command-line entry point for source-grounded bid field extraction."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.search.config import index_path
from src.search.storage import CorpusStore

from .config import output_root
from .extractor import StructuredExtractor
from .serialization import write_record


def main(argv=None) -> int:
    """Load indexed evidence, extract one bid, and write its JSON record.

    Args:
        argv: Optional argument sequence; ``None`` parses process arguments.
            The ``extract`` subcommand accepts required ``--input`` and
            optional ``--output`` directory arguments.

    Returns:
        Process status code 0 after printing the structured-record path.

    Raises:
        OSError: If the index or output cannot be read/written.
        ValueError: If the input index or extracted record is invalid.
    """
    parser = argparse.ArgumentParser(prog="python -m src.extraction.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--input", required=True)
    extract.add_argument("--output", default=str(output_root()))
    args = parser.parse_args(argv)
    if args.command == "extract":
        bid_id = Path(args.input).name
        records = CorpusStore(index_path()).load().records
        evidence = [
            {"record": item.__dict__, "authority_status": item.status}
            for item in records
            if item.bid_id == bid_id
        ]
        record = StructuredExtractor().extract(args.input, evidence)
        print(write_record(record, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
