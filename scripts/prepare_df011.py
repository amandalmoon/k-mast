"""Offline frozen expansion/cache plan. No authentication or price transport exists here."""

import json
from datetime import date
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from scripts.run_df005 import load_histories


def guard_unapproved_expansion(plan):
    if not plan.get("execution_authorized") or not plan.get("separate_user_approval_reference"):
        raise PermissionError("DF011_PRICE_SCOPE_REQUIRES_SEPARATE_APPROVAL")
    raise PermissionError("DF011_HAS_NO_NEW_AUTHENTICATED_COLLECTOR")


def main():
    public = Path("artifacts/df011")
    protocol = json.loads((public / "DF011_PROTOCOL.json").read_bytes())
    panel = json.loads(Path("data/data-first-private-df005-panel/manifest.json").read_bytes())
    private = Path("data/data-first-private-df011-cache")
    rows, requests = [], []
    for target in protocol["expansion_targets"]:
        symbol = target["historical_short_code"]
        start, end = (date.fromisoformat(target[k]) for k in ("start", "end"))
        idx = "0001" if target["then_market"] == "KOSPI" else "1001"
        stock_counts = {}
        for basis in ("RAW", "ADJUSTED"):
            stock = tuple(
                r for r in load_histories(panel, symbol, basis) if start <= r.exchange_date <= end
            )
            stock_counts[basis] = len(stock)
            if not stock:
                requests.append(
                    dict(
                        symbol=symbol,
                        operation="daily",
                        basis=basis,
                        start=str(start),
                        end=str(end),
                        expected_pages=1,
                    )
                )
        history = load_histories(panel, idx, "RAW")
        index = tuple(r for r in history if start <= r.exchange_date <= end)
        encoded = canonical([r.model_dump(mode="json") for r in index])
        filename = target["receipt"] + "-index.json"
        immutable_write(private / filename, encoded)
        missing = None
        if start < history[0].exchange_date:
            # This is a request interval, never a generated market-session calendar.
            missing = dict(
                symbol=idx,
                operation="index_daily",
                basis="RAW",
                start=str(start),
                end="2022-08-31",
                expected_pages=1,
            )
            requests.append(missing)
        rows.append(
            dict(
                target=target,
                cached_stock_rows=stock_counts,
                cached_index_rows=len(index),
                index_symbol=idx,
                index_first=str(index[0].exchange_date),
                index_last=str(index[-1].exchange_date),
                index_sha256=digest(encoded),
                private_index_file=filename,
                missing_index_request=missing,
                price_qualification="DATA_PENDING",
                action_halt_scope=dict(start=str(start), end=str(end), verified=False),
            )
        )
    plan = dict(
        version="DF011_CACHE_ADJUSTED_PRICE_PROPOSAL_V1",
        execution_authorized=False,
        separate_user_approval_reference=None,
        unused_df010_budget_carried=False,
        protocol_sha256=digest((public / "DF011_PROTOCOL.json").read_bytes()),
        targets=rows,
        requests=requests,
        paths=protocol["price_plan"],
        expected_stock_pages=sum(r["operation"] == "daily" for r in requests),
        expected_index_pages=sum(r["operation"] == "index_daily" for r in requests),
        maximum_authentication=2,
        retry_inclusive_total_ceiling=2 + 2 * len(requests),
        maximum_attempts_per_page=2,
        minimum_response_completion_wait_seconds="3.10",
        environment="PAPER_READ_ONLY",
        authentication_executed=0,
        requests_executed=0,
        storage="data/data-first-private-df011-prices (future approved run only; Git excluded)",
        transport="NOT_IMPLEMENTED_IN_DF011; proposal cannot send authenticated requests",
        limitations="No stock substitution; complete PIT halt calendars remain unknown",
    )
    atomic_json(public / "next-price-proposal.json", plan)
    print(
        json.dumps(
            {
                k: plan[k]
                for k in (
                    "expected_stock_pages",
                    "expected_index_pages",
                    "maximum_authentication",
                    "retry_inclusive_total_ceiling",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
