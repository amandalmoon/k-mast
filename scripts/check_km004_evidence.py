"""Independent JSON/Decimal arithmetic, with no production imports."""

import json
from decimal import Decimal as D
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parents[1] / "artifacts/km004/joint-v1"
    summary = json.loads((folder / "summary.json").read_bytes())
    state = json.loads((folder / "final-state.json").read_bytes())
    panel = json.loads((folder / "panel.json").read_bytes())
    account = state["account"]
    assert sum(D(x["fee"]) + D(x["tax"]) for x in state["settlements"]) == D(".35")
    assert D(account["dividends"]) == 20
    assert D(account["account_opex"]) == 5 and D(state["external_opex"]) == 10
    assert D(summary["account_net_pnl"]) == 20 - D(".35") - 5
    assert D(summary["project_net_pnl"]) == D(summary["account_net_pnl"]) - 10
    assert len(panel) == 7 and panel[-1]["account_nav"] == summary["account_nav"]
    weights = {"A": D(".4"), "B": D(".3"), "C": D(".2"), "D": D(".05")}
    weighted = sum((D(nav) - 10000) * weights[s] for s, nav in panel[-1]["reference_navs"].items())
    weighted += (D(panel[-1]["cash_nav"]) - 10000) * D(".05")
    assert weighted == D(summary["weighted_reference_net"])
    assert summary["actual_broker_orders"] == 0
    assert summary["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    risk = json.loads((folder.parent / "risk-diagnostic.json").read_bytes())
    proposal = risk["proposal"]
    weights_risk = [D(w) for _, w in proposal["weights"]]
    covariance = [[D(c) for c in row] for row in proposal["covariance"]]
    variance = sum(
        weights_risk[i] * covariance[i][j] * weights_risk[j]
        for i in range(len(weights_risk))
        for j in range(len(weights_risk))
    )
    assert abs(variance - D(proposal["variance"])) < D("1e-24")
    assert abs(sum(D(c) for _, c in proposal["risk_contributions"]) - variance.sqrt()) < D("1e-24")
    assert sum(weights_risk) + D(proposal["cash_weight"]) == 1
    assert risk["real_panel"]["status"] == "HOLD" and risk["promotion"] == "DISABLED"
    print("Independent account/reference/cost conservation: PASS")


if __name__ == "__main__":
    main()
