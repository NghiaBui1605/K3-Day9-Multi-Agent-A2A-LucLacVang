"""Command-line entry point for the Olist dispute-resolution pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from dispute_pipeline import generate_mock_cases, process_directory


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-mocks", action="store_true", help="create 50 local development cases")
    parser.add_argument("--overwrite-mocks", action="store_true", help="allow replacing existing EC input files")
    parser.add_argument("--process", action="store_true", help="process all input/EC_*.json files")
    args = parser.parse_args()
    if not args.generate_mocks and not args.process:
        parser.error("choose --generate-mocks and/or --process")
    if args.overwrite_mocks and not args.generate_mocks:
        parser.error("--overwrite-mocks requires --generate-mocks")
    if args.generate_mocks:
        count = generate_mock_cases(ROOT / "data", ROOT / "input", args.overwrite_mocks)
        print(f"Generated {count} mock input cases.")
    if args.process:
        count = process_directory(ROOT / "data", ROOT / "input", ROOT / "output", ROOT / "logging")
        print(f"Processed {count} cases.")


if __name__ == "__main__":
    main()
