"""Command-line entry point for deterministic offline AHA case reviews."""
from __future__ import annotations

import argparse

from .engine import load_case, write_review_package
from .models import CaseValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an offline AHA Pattern Donation case.")
    parser.add_argument("case_file")
    parser.add_argument("output_root")
    args = parser.parse_args()
    try:
        result = write_review_package(load_case(args.case_file), args.output_root)
    except CaseValidationError as exc:
        parser.error(str(exc))
    print(result["disposition"])
    return 0
