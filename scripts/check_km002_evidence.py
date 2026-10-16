"""Independent raw-JSON accounting check, without importing the production ledger/risk code."""

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def main():
    root = Path(sys.argv[1])
    expected = {
        "A": (0, "10016"),
        "B": (170, "9996"),
        "C": (4, "9999"),
        "D": (0, "10000"),
        "E": (50, "10500"),
        "F": (100, "9499"),
    }
    for case, (quantity, expected_nav) in expected.items():
        folder = root / case
        state = json.loads((folder / "final-state.json").read_bytes())
        manifest = json.loads((folder / "manifest.json").read_bytes())
        events = json.loads((folder / "events.json").read_bytes())
        prices = {q["symbol"]: Decimal(q["price"]) for q in state["quotes"]}

        def nav(book, prices=prices):
            return (
                Decimal(book["settled_cash"])
                + Decimal(book["unsettled_receivables"])
                - Decimal(book["unsettled_payables"])
                + Decimal(book["dividend_receivable"])
                - Decimal(book["other_liabilities"])
                - Decimal(book["fees_payable"])
                - Decimal(book["taxes_payable"])
                + sum(lot["quantity"] * prices[lot["symbol"]] for lot in book["lots"])
            )

        book = state["account"]
        assert nav(book) == Decimal(expected_nav)
        assert sum(lot["quantity"] for lot in book["lots"]) == quantity
        assert nav(book) == sum(nav(a["book"]) for a in state["attribution"])
        unrealized = sum(
            lot["quantity"] * (prices[lot["symbol"]] - Decimal(lot["unit_cost"]))
            for lot in book["lots"]
        )
        economic = (
            Decimal(book["realized_pnl"])
            + unrealized
            + Decimal(book["interest"])
            + Decimal(book["dividends"])
            - Decimal(book["fees_and_taxes"])
            - Decimal(book["account_opex"])
        )
        assert economic == nav(book) - Decimal(book["capital_flows"])
        assert digest(state) == manifest["output_hash"]
        assert len({e["event_id"] for e in events}) == len(events) == manifest["events"]
        assert manifest["reference"]["ledger_type"] == "REFERENCE"
        assert manifest["live_approved"] is False
        if case == "C":
            assert Decimal(book["reserved_buy_cash"]) == 64
        if case == "F":
            assert book["lots"] and state["quotes"][0]["halted"]
        print(f"{case}: PASS raw JSON quantity={quantity}, NAV={nav(book)}, economic={economic}")
    print("PASS: independent arithmetic, attribution, synthetic outcome and hash checks")


if __name__ == "__main__":
    main()
