from __future__ import annotations

import argparse
from pathlib import Path

from ecommerce_disputes.runner import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve all Olist e-commerce dispute cases")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--logging", type=Path, default=Path("logging"))
    parser.add_argument("--zip", type=Path, default=Path("output.zip"))
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Offline diagnostic mode only; submission runs should use the default LLM mode",
    )
    args = parser.parse_args()
    count = run(
        args.input,
        args.data,
        args.output,
        args.logging,
        args.zip,
        use_llm=not args.no_llm,
    )
    print(f"Processed and verified {count} cases; submission: {args.zip}")


if __name__ == "__main__":
    main()
