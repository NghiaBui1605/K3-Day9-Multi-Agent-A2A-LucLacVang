"""Regression tests for the deterministic policy and verifier pipeline."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dispute_pipeline import Dataset, collect_facts, process_case, verifier_agent  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
