from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .coordinator import CoordinatorAgent, load_cases
from .repository import OlistRepository
from .settings import MODEL_NAME, MODEL_PARAMETER_COUNT
from .tracing import TraceWriter


def run(
    input_dir: Path,
    data_dir: Path,
    output_dir: Path,
    logging_dir: Path,
    zip_path: Path | None = None,
) -> int:
    cases = load_cases(input_dir)
    expected_names = [f"EC_{number:03d}.json" for number in range(1, 51)]
    actual_names = [path.name for path, _ in cases]
    if actual_names != expected_names:
        raise ValueError(
            "input must contain exactly EC_001.json through EC_050.json; "
            f"found {len(actual_names)} case files"
        )
    if len({case.case_id for _, case in cases}) != 50:
        raise ValueError("case_id values must be unique")
    for path, case in cases:
        if case.case_id != path.stem:
            raise ValueError(f"case_id does not match filename: {path}")

    repository = OlistRepository(data_dir, (case.claimed_order_id for _, case in cases))
    trace = TraceWriter(logging_dir / "trace.jsonl")
    coordinator = CoordinatorAgent(repository, trace)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.iterdir():
        if stale.is_file() and (stale.name.startswith("EC_") or stale.name == ".gitkeep"):
            stale.unlink()

    for path, case in cases:
        result = coordinator.process(case)
        destination = output_dir / path.name
        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    metadata = {
        "model": MODEL_NAME,
        "parameter_count": MODEL_PARAMETER_COUNT,
        "parameter_size": "0B",
        "provider": "local",
        "framework": "Python standard library; explicit multi-agent handoffs",
        "runtime": "Python 3.10+",
        "policy_version": "EC_POLICY_V1",
        "cases_processed": len(cases),
    }
    logging_dir.mkdir(parents=True, exist_ok=True)
    with (logging_dir / "metadata.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    if zip_path is not None:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in expected_names:
                archive.write(output_dir / name, arcname=name)
    return len(cases)
