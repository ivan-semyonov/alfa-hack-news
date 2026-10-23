#!/usr/bin/env python3
"""Inspect supplied CSVs without assuming filename or loading sensitive rows."""
import argparse, csv, json
from pathlib import Path
COMPANIES = {'SYNTHETIC_U', 'MAINOKVED_CODE', 'REGION'}
PERSONS = {'SYNTHETIC_F', 'SYNTHETIC_U'}
PAYMENTS = {'PAYER', 'BENEFICIARY', 'PAY_AMT', 'PAY_CNT'}


def inspect(path: Path) -> dict:
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        sniff = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sniff, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        headers = set(reader.fieldnames or [])
        kinds = {'companies': COMPANIES, 'persons': PERSONS, 'payments': PAYMENTS}
        matches = [kind for kind, required in kinds.items() if required <= headers]
        count = sum(1 for _ in reader)
        return {'path': str(path), 'detected_types': matches, 'columns': sorted(headers),
                'rows': count, 'warnings': [] if matches else ['Unknown/incomplete CSV schema']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CSV preflight; outputs metadata only')
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([inspect(x) for x in args.files], ensure_ascii=False, indent=2))
