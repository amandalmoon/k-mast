"""Raw-JSON arithmetic checker, independent of alpha/reference implementation imports."""

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def verify_reference(state):
    prices = {symbol: Decimal(price) for symbol, price, _ in state["marks"]}
    market = sum(lot["quantity"] * prices[lot["symbol"]] for lot in state["lots"])
    unrealized = sum(
        lot["quantity"] * (prices[lot["symbol"]] - Decimal(lot["unit_cost"]))
        for lot in state["lots"]
    )
    nav = Decimal(state["cash"]) + market
    assert nav == Decimal(state["panel"][-1]["nav"])
    net = nav - Decimal(state["capital"])
    assert net == (
        Decimal(state["realized"])
        + unrealized
        + Decimal(state["dividends"])
        - Decimal(state["costs"])
        - Decimal(state["operating_costs"])
    )
    assert len(state["panel"]) == 3 and state["ledger_type"] == "REFERENCE"
    assert len({item[0] for item in state["facts"]}) == len(state["facts"])
    return nav, net


def main():
    root = Path(sys.argv[1])
    summary = json.loads((root / "summary.json").read_bytes())
    assert summary["real_market_rows"] == 0 and summary["economics"] == "ECONOMIC_EDGE_UNVERIFIED"
    for strategy in "ABCD":
        state = json.loads((root / strategy / "reference.json").read_bytes())
        nav, net = verify_reference(state)
        metrics = summary["strategies"][strategy]
        assert digest(state) == metrics["output_hash"]
        assert (
            digest(json.loads((root / strategy / "context.json").read_bytes()))
            == metrics["input_hash"]
        )
        assert net == Decimal(metrics["NET_OPERATING_PNL_KRW"])
        assert metrics["data_status"] == "DATA_BLOCKED" and metrics["economic_status"] == "HOLD"
        assert Decimal(metrics["cash_excess_krw"]) == net + Decimal(state["operating_costs"])
        print(f"{strategy}: PASS synthetic NAV={nav}, net={net}, HOLD")
    fixed = sum(
        (
            verify_reference(json.loads((root / "fixed-budget" / (s + ".json")).read_bytes()))[0]
            for s in "ABCD"
        ),
        Decimal("499.85"),
    )
    assert fixed == Decimal(summary["baselines"]["fixed_budget_reference"]["closing_nav"])
    state = json.loads((root / "mock-state.json").read_bytes())
    assert digest(state) == summary["mock_integration"]["state_hash"]
    assert sum(lot["quantity"] for lot in state["account"]["lots"]) == 15
    assert (
        sum(sum(lot["quantity"] for lot in a["book"]["lots"]) for a in state["attribution"]) == 15
    )
    assert Decimal(state["account"]["fees_and_taxes"]) == 1
    print("PASS: reference equations, fixed-budget capital, hashes and Mock attribution")


if __name__ == "__main__":
    main()
