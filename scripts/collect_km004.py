"""Bounded private KIS daily vertical slice; no account, order, arbitrary route or secret output."""

import argparse
import json
import time
from datetime import timedelta
from pathlib import Path

from kmast.brokers.kis.adapter import AccountRateLimiter, RatePolicy, TokenManager
from kmast.brokers.kis.network import KISAuth, MarketClient, NetworkPermit, NetworkPolicy, Wire
from kmast.brokers.kis.requests import MarketRequest
from kmast.core.clock import SystemClock
from kmast.data.models import KST, Provenance
from kmast.data.normalization import content_hash
from kmast.data.pipeline import collect_rest
from kmast.data.store import DataStore, canonical, digest, scrub
from scripts.read_kis_env import load_env


def main():
    # Invoked explicitly for KM-004, under the user's existing market-read authorization.
    clock = SystemClock()
    now = clock.now()
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-dir", type=Path)
    args = parser.parse_args()
    output = args.resume_dir or Path("data") / ("km004-private-" + now.strftime("%Y%m%dT%H%M%S%fZ"))
    if args.resume_dir:
        if output.resolve().parent != (Path.cwd() / "data").resolve() or not output.name.startswith(
            "km004-private-"
        ):
            raise SystemExit("resume outside explicit private workspace scope")
    else:
        output.mkdir(parents=True, exist_ok=False)
    proof = Path("artifacts/km004")
    permit = NetworkPermit(
        NetworkPolicy(
            allow_network_readonly=True,
            symbols=("005930", "0001"),
            max_requests=5,
            max_days=90,
            max_attempts=1,
        )
    )
    counts = {
        "auth_attempts": 0,
        "market_attempts": 0,
        "order_calls": 0,
        "cancel_calls": 0,
        "account_queries": 0,
    }

    class MarketOnlyWire(Wire):
        def send(self, config, method, path, headers, payload):
            if method == "POST" and path == "/oauth2/tokenP":
                counts["auth_attempts"] += 1
            elif method == "GET" and path in {
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            }:
                counts["market_attempts"] += 1
            else:
                raise PermissionError("outside vertical-slice capability")
            return super().send(config, method, path, headers, payload)

    records = []
    result = {
        "collected_at": now.isoformat(),
        "scope": "PRIVATE_VERTICAL_SLICE_NOT_UNIVERSE",
        "license_status": "LICENSE_HOLD",
        "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
        "live_status": "LIVE_NOT_APPROVED",
        "market_data_redistributed": False,
    }
    try:
        config = load_env(Path.home() / ".kmast-readonly/.env")
        wire = MarketOnlyWire(permit)
        client = MarketClient(
            config,
            wire,
            TokenManager(config, KISAuth(wire, clock), clock),
            AccountRateLimiter(time.monotonic),
            RatePolicy(interval_seconds=3, evidence_ref="CONSERVATIVE_NOT_GUARANTEED_QUOTA"),
            clock,
        )
        end = now.astimezone(KST).date() - timedelta(days=1)
        start = end - timedelta(days=89)
        requests = [
            MarketRequest(operation="daily", symbol="005930", start=start, end=end),
            MarketRequest(
                operation="daily", symbol="005930", start=start, end=end, price_basis="ADJUSTED"
            ),
            MarketRequest(operation="index_daily", symbol="0001", start=start, end=end),
        ]
        secrets = tuple(
            s.get_secret_value()
            for s in (config.app_key, config.app_secret, config.account_ref)
            if s
        )
        store = DataStore(output)
        for index, request in enumerate(requests):
            if index:
                time.sleep(3)
            identity = "km004:" + content_hash(request.model_dump(mode="json"))
            continuation = []

            def acquire(request=request, continuation=continuation, identity=identity):
                before = clock.now()
                reply = client.read(request)
                received = clock.now()
                continuation.append(reply.continuation)
                return reply.body, Provenance(
                    source="KIS",
                    endpoint=request.path,
                    tr_id=request.tr_id,
                    symbol=request.symbol,
                    venue="KRX",
                    session="UNKNOWN",
                    request_time=before,
                    received_at=received,
                    acquired_at=received,
                    source_hash=digest(canonical(scrub(reply.body, secrets))),
                    ingestion_run_id=content_hash([identity, before.isoformat()]),
                    request_fingerprint=content_hash(request.model_dump(mode="json")),
                    data_origin="KIS_READONLY",
                )

            dataset, rows = collect_rest(store, identity, request, acquire, secrets)
            records.append(
                {
                    "operation": request.operation,
                    "symbol": request.symbol,
                    "price_basis": request.price_basis,
                    "request": request.model_dump(mode="json"),
                    "dataset_id": dataset,
                    "row_count": len(rows),
                    "start": str(min(r.exchange_date for r in rows)) if rows else None,
                    "end": str(max(r.exchange_date for r in rows)) if rows else None,
                    "flags": sorted({f for r in rows for f in r.quality_flags}),
                    "continuation": continuation,
                    "missing_rate": None,
                    "coverage": "EXPECTED_KRX_GRID_UNVERIFIED",
                }
            )
            # The verified response contained 50 index rows despite an empty continuation header.
            # One bounded backward date slice tests continuity; never infer a complete KRX grid.
            if request.operation == "index_daily" and len(requests) < 4 and rows:
                earliest = min(row.exchange_date for row in rows)
                if earliest > start:
                    requests.append(
                        MarketRequest(
                            operation="index_daily",
                            symbol="0001",
                            start=start,
                            end=earliest - timedelta(days=1),
                        )
                    )
        result["status"] = "DATA_PARTIAL_LICENSE_HOLD"
        assert not any(
            s.encode() in p.read_bytes() for p in output.rglob("*") if p.is_file() for s in secrets
        )
    except Exception:
        result["status"] = "PARTIAL_OR_FAILED_CLOSED"
        result["reason"] = "INPUT_OR_ACQUISITION_CHECK_FAILED_RAW_INPUTS_SUPPRESSED"
    result.update(counts)
    result["network_requests_used"] = permit.used
    result["datasets"] = records
    result["total_real_rows"] = sum(r["row_count"] for r in records)
    result["private_store"] = output.as_posix()
    result["interpretation"] = "Raw prices are not historical PIT releases or executable quotes"
    record_name = "collection-resumed.json" if args.resume_dir else "collection.json"
    (output / record_name).write_bytes(canonical(result))
    (proof / ("real-collection-" + now.strftime("%Y%m%dT%H%M%SZ") + ".json")).write_bytes(
        canonical(result)
    )
    (proof / "real-collection.json").write_bytes(canonical(result))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "DATA_PARTIAL_LICENSE_HOLD" else 1)


if __name__ == "__main__":
    main()
