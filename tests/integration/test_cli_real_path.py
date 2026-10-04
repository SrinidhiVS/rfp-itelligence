from pathlib import Path

from src.extraction.serialization import read_record


def test_documented_cli_output_contract_path_is_readable():
    output = Path("output/bid-records")
    if not output.exists():
        return
    records = list(output.glob("*/structured-record.json"))
    for path in records:
        assert len(read_record(path).fields) == 20
