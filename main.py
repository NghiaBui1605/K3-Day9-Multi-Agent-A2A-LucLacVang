"""
main.py – Main runner for the Multi-Agent E-commerce Dispute Resolution system.

Processes all 50 cases in input/ sequentially, writes outputs to output/,
and produces trace.jsonl for auditing.

Usage:
    python main.py                 # process all cases
    python main.py --case EC_001   # process single case
    python main.py --dry-run       # validate first case only
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from agents.coordinator import CoordinatorAgent

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_DIR = Path("logging")
LOG_DIR.mkdir(exist_ok=True)

# Use utf-8 stdout to avoid cp1252 errors on Windows
import io
_stdout_handler = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace"))
_stdout_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))

_file_handler = logging.FileHandler(LOG_DIR / "run.log", mode="w", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_stdout_handler, _file_handler],
)
logger = logging.getLogger("main")

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
TRACE_FILE = Path("trace.jsonl")


def load_cases(case_id: str | None = None) -> list[dict]:
    """Load input cases from input/ directory."""
    if case_id:
        path = INPUT_DIR / f"{case_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Case file not found: {path}")
        with open(path, encoding="utf-8") as f:
            return [json.load(f)]

    cases = []
    for i in range(1, 51):
        path = INPUT_DIR / f"EC_{i:03d}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                cases.append(json.load(f))
        else:
            logger.warning(f"Missing input file: {path}")
    return cases


def run(args):
    case_id = getattr(args, "case", None)
    dry_run = getattr(args, "dry_run", False)

    # Load cases
    cases = load_cases(case_id)
    if dry_run:
        cases = cases[:1]
        logger.info("=== DRY RUN MODE (first case only) ===")

    if not cases:
        logger.error("No input cases found. Run generate_inputs.py first.")
        sys.exit(1)

    logger.info(f"Processing {len(cases)} cases...")

    coordinator = CoordinatorAgent()
    traces = []
    success = 0
    errors = 0

    overall_start = time.time()

    # Open trace file for writing (overwrite previous run)
    with open(TRACE_FILE, "w", encoding="utf-8") as trace_f:
        for idx, case in enumerate(cases, start=1):
            cid = case.get("case_id", f"UNKNOWN_{idx}")
            logger.info(f"\n{'='*60}")
            logger.info(f"Case {idx}/{len(cases)}: {cid}")
            logger.info(f"{'='*60}")

            try:
                trace = coordinator.run(case)
                traces.append(trace)
                trace_f.write(json.dumps(trace, ensure_ascii=False) + "\n")
                trace_f.flush()
                success += 1

                # Print summary
                fd = trace.get("final_output", {})
                assessment = fd.get("assessment", {})
                fin = fd.get("financial_resolution", {})
                logger.info(
                    f"[OK] {cid}: {assessment.get('primary_issue')} | "
                    f"refund={fin.get('recommended_refund_brl')} BRL | "
                    f"confidence={assessment.get('confidence')}"
                )

            except Exception as e:
                logger.exception(f"❌ Error processing {cid}: {e}")
                errors += 1
                # Write error trace
                error_trace = {
                    "case_id": cid,
                    "error": str(e),
                    "steps": [],
                }
                trace_f.write(json.dumps(error_trace, ensure_ascii=False) + "\n")
                trace_f.flush()

    elapsed = round(time.time() - overall_start, 1)

    # ── Final summary ──────────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETED in {elapsed}s")
    logger.info(f"  Success: {success}/{len(cases)}")
    logger.info(f"  Errors:  {errors}/{len(cases)}")
    logger.info(f"  Output:  {OUTPUT_DIR}/")
    logger.info(f"  Trace:   {TRACE_FILE}")
    logger.info(f"{'='*60}")

    # Verify output count
    out_files = list(OUTPUT_DIR.glob("EC_*.json"))
    logger.info(f"  Output files written: {len(out_files)}")

    if errors > 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent E-commerce Dispute Resolution System"
    )
    parser.add_argument(
        "--case", type=str, default=None,
        help="Process a single case (e.g. EC_001)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process only the first case (for testing)"
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
