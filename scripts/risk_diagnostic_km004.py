"""Small covariance arithmetic fixture; no fitting to the acquired market sample."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from kmast.core.contracts import ReturnUnits
from kmast.portfolio.allocation import ReturnSeries, RiskSettings, freeze_mock_fixed, risk_candidate


def main():
    at = datetime(2026, 10, 16, tzinfo=UTC)
    times = tuple(at - timedelta(days=i) for i in (3, 2, 1))
    units = ReturnUnits(
        horizon=timedelta(days=1),
        capital_basis="REFERENCE_NAV",
        capital_policy_id="SYNTHETIC_FIXED",
        valuation_calendar="SYNTHETIC_EXPLICIT_DATES",
        cost_model_version="SYNTHETIC_V1",
        risk_basis="REFERENCE_NAV",
        ledger_type="REFERENCE",
    )
    series = tuple(
        ReturnSeries(
            strategy=s,
            units=units,
            at=times,
            known_at=times,
            returns=tuple(map(D, values)),
            origin="SYNTHETIC",
            evidence_ref="ARITHMETIC_ONLY",
        )
        for s, values in (("A", (".01", "-.01", ".02")), ("B", (".02", "-.02", ".01")))
    )
    settings = RiskSettings(
        version="SYNTHETIC_ONLY",
        min_samples=3,
        caps=(("A", D(".4")), ("B", D(".4"))),
        risk_budgets=(("A", D(".5")), ("B", D(".5"))),
    )
    proposal = risk_candidate(series, settings, at)
    frozen = freeze_mock_fixed(proposal, "SYNTHETIC_EXPLICIT_DIAGNOSTIC")
    result = {
        "proposal": proposal.model_dump(mode="json"),
        "mock_fixed_freeze": frozen.model_dump(mode="json"),
        "real_panel": risk_candidate((), settings, at).model_dump(mode="json"),
        "promotion": "DISABLED",
        "economics": "UNVERIFIED",
    }
    path = Path(__file__).resolve().parents[1] / "artifacts/km004/risk-diagnostic.json"
    path.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
    print("Synthetic covariance diagnostic: PROPOSAL_ONLY; real panel: HOLD")


if __name__ == "__main__":
    main()
