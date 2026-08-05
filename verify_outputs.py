from __future__ import annotations

import json
from pathlib import Path

from ecommerce_disputes.agents import DeliveryAgent, OrderSellerAgent, PaymentAgent, PolicyAgent
from ecommerce_disputes.coordinator import load_cases
from ecommerce_disputes.repository import OlistRepository
from ecommerce_disputes.verifier import VerifierAgent


def main() -> None:
    cases = load_cases(Path("input"))
    repository = OlistRepository(Path("data"), (case.claimed_order_id for _, case in cases))
    expected = {path.name: case for path, case in cases}
    actual = sorted(Path("output").glob("EC_*.json"))
    if [path.name for path in actual] != sorted(expected):
        raise SystemExit("output filenames do not match input filenames")
    verifier = VerifierAgent()
    for path in actual:
        with path.open("r", encoding="utf-8") as handle:
            result = json.load(handle)
        case = expected[path.name]
        if result.get("case_id") != case.case_id:
            raise SystemExit(f"case_id mismatch in {path}")
        order = OrderSellerAgent().investigate(repository, case.claimed_order_id)
        payment = PaymentAgent().investigate(repository, case.claimed_order_id)
        delivery = DeliveryAgent().investigate(order)
        decision = PolicyAgent().decide(order, payment, delivery)
        recomputed = verifier.assemble(case, order, payment, delivery, decision)
        if result != recomputed:
            raise SystemExit(f"saved output differs from independently recomputed result: {path}")
        verifier.validate_external(result, repository)
    print(
        f"Verified {len(actual)} output files, all financial fields, decisions, "
        "entity sets, and evidence IDs"
    )


if __name__ == "__main__":
    main()
