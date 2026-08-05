from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .coordinator import CoordinatorAgent, load_cases
from .llm import OpenAILLMClient
from .repository import OlistRepository
from .settings import LLM_PROVIDER, MODEL_NAME, MODEL_PARAMETER_COUNT
from .tracing import TraceWriter


def run(
    input_dir: Path,
    data_dir: Path,
    output_dir: Path,
    logging_dir: Path,
    zip_path: Path | None = None,
    use_llm: bool = True,
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

    # Validate credentials before truncating trace or touching previous artifacts.
    llm = OpenAILLMClient.from_env() if use_llm else None
    repository = OlistRepository(data_dir, (case.claimed_order_id for _, case in cases))
    trace = TraceWriter(logging_dir / "trace.jsonl")
    coordinator = CoordinatorAgent(repository, trace, llm)

    # Keep the previous submission intact if an API call or verification fails mid-run.
    results: list[tuple[str, dict]] = []
    for path, case in cases:
        result = coordinator.process(case)
        results.append((path.name, result))

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.iterdir():
        if stale.is_file() and (stale.name.startswith("EC_") or stale.name == ".gitkeep"):
            stale.unlink()
    for filename, result in results:
        destination = output_dir / filename
        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    metadata = {
        "model": MODEL_NAME,
        "parameter_count": MODEL_PARAMETER_COUNT,
        "parameter_size": f"{MODEL_PARAMETER_COUNT // 1_000_000_000}B" if MODEL_PARAMETER_COUNT else "not disclosed",
        "provider": LLM_PROVIDER if use_llm else "disabled for offline verification",
        "llm_enabled": use_llm,
        "framework": "Python standard library; LLM policy agent with deterministic verifier",
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
                archive.write(output_dir / name, arcname=f"output/{name}")
    return len(cases)
