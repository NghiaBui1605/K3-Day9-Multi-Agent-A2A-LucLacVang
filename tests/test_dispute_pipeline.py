"""Regression tests for the deterministic policy and verifier pipeline."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dispute_pipeline import (  # noqa: E402
    Dataset,
    collect_facts,
    process_case,
    process_directory,
    verifier_agent,
)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = Dataset.load(ROOT / "data")

    def test_all_fifty_cases_pass_source_backed_verification(self) -> None:
        input_files = sorted((ROOT / "input").glob("EC_*.json"))
        self.assertEqual(50, len(input_files))
        for input_file in input_files:
            with self.subTest(case=input_file.stem):
                case = json.loads(input_file.read_text(encoding="utf-8"))
                result, trace = process_case(self.dataset, case)
                self.assertEqual(input_file.stem, result["case_id"])
                self.assertEqual(1.0, result["assessment"]["confidence"])
                self.assertTrue(trace["verified"])

    def test_verifier_rejects_fabricated_evidence(self) -> None:
        case = json.loads((ROOT / "input" / "EC_001.json").read_text(encoding="utf-8"))
        result, _ = process_case(self.dataset, case)
        order_id = case["customer_request"]["claimed_order_id"]
        facts = collect_facts(self.dataset, order_id)
        result = copy.deepcopy(result)
        result["evidence_ids"][0] = "order:not-a-real-order"
        with self.assertRaisesRegex(ValueError, "Evidence ID"):
            verifier_agent(result, facts)

    def test_payment_entity_and_evidence_ids_are_canonically_sorted(self) -> None:
        case = json.loads((ROOT / "input" / "EC_004.json").read_text(encoding="utf-8"))
        result, _ = process_case(self.dataset, case)
        order_id = case["customer_request"]["claimed_order_id"]
        self.assertEqual(
            [f"{order_id}:1", f"{order_id}:2"],
            result["affected_entities"]["payment_ids"],
        )
        payment_evidence = [
            evidence for evidence in result["evidence_ids"] if evidence.startswith("payment:")
        ]
        self.assertEqual(
            [f"payment:{order_id}:1", f"payment:{order_id}:2"], payment_evidence
        )

    def test_openrouter_mode_records_real_agent_contract_shape(self) -> None:
        class FakeClient:
            model = "qwen/qwen3-8b"

            def __init__(self) -> None:
                self.calls = 0
                self.lock = threading.Lock()

            def complete(
                self,
                _messages: list[dict[str, str]],
                max_tokens: int = 450,
                json_mode: bool = False,
            ) -> str:
                with self.lock:
                    self.calls += 1
                return json.dumps({
                    "summary": "verified",
                    "observations": [],
                    "evidence_ids": [],
                    "open_questions": [],
                })

        client = FakeClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            count = process_directory(
                ROOT / "data",
                ROOT / "input",
                temporary / "output",
                temporary / "logging",
                llm_client=client,
                workers=4,
            )
            metadata = json.loads(
                (temporary / "logging" / "metadata.json").read_text(encoding="utf-8")
            )
            traces = [
                json.loads(line)
                for line in (temporary / "logging" / "trace.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
        self.assertEqual(50, count)
        self.assertEqual(250, client.calls)
        self.assertEqual("openrouter_multi_agent", metadata["execution_mode"])
        self.assertTrue(all(len(trace["llm_handoffs"]) == 4 for trace in traces))
        self.assertTrue(all(trace["llm_verified"] for trace in traces))


if __name__ == "__main__":
    unittest.main()
