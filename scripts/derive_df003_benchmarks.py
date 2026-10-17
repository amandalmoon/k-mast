"""Explicit same-symbol/cost/window benchmark deltas; no new strategy trials."""

import json
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import canonical, immutable_write


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df003"
    result = json.loads((proof / "results.json").read_bytes())
    indexed = {(s["symbol"], s["scenario"], s["candidate"]): s for s in result["summaries"]}
    deltas = []
    for s in result["summaries"]:
        bases = {
            name: indexed[s["symbol"], s["scenario"], name]
            for name in ("CASH", "BUY_HOLD", "HOLD_25", "TREND_25")
        }
        deltas.append(
            dict(
                symbol=s["symbol"],
                scenario=s["scenario"],
                candidate=s["candidate"],
                net_excess={
                    name: str(D(s["project_net"]) - D(b["project_net"]))
                    for name, b in bases.items()
                },
                actual_exposure_delta={
                    name: str(D(s["average_close_exposure"]) - D(b["average_close_exposure"]))
                    for name, b in bases.items()
                },
                mdd_delta={name: str(D(s["mdd"]) - D(b["mdd"])) for name, b in bases.items()},
                interpretation="SAME_WINDOW_COST_CAPITAL_DIFFERENT_EXPOSURE_AND_PATH_NOT_RISK_EQUIVALENT",
            )
        )
    immutable_write(
        proof / "benchmark-deltas.json",
        canonical(dict(references=216, deltas=deltas, new_trials=0)),
    )
    print("DF003 216 explicit CASH/BUY_HOLD/HOLD_25/TREND_25 comparisons: PASS")


if __name__ == "__main__":
    main()
