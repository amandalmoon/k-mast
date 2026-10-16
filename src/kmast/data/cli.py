import argparse
import json
import time
from datetime import UTC, date, datetime
from datetime import time as local_time
from importlib.resources import files
from pathlib import Path
from typing import Any

from kmast.brokers.kis.adapter import AccountRateLimiter, RatePolicy, TokenManager
from kmast.brokers.kis.network import KISAuth, MarketClient, NetworkPermit, NetworkPolicy, Wire
from kmast.brokers.kis.requests import MarketRequest
from kmast.brokers.kis.stream import WS_COLUMNS, parse_frame
from kmast.core.clock import SystemClock
from kmast.core.config import BrokerConfig
from kmast.data.dart import DisclosureRegistry, parse_disclosure
from kmast.data.models import EconomicSource, Observation, Provenance
from kmast.data.normalization import content_hash
from kmast.data.pipeline import collect_rest
from kmast.data.readiness import AvailabilityEntry, build_matrix
from kmast.data.store import DataStore, canonical, digest, immutable_write, scrub


def fixture_run(output: Path) -> dict[str, Any]:
    fixture = json.loads(
        files("kmast.data").joinpath("fixtures/market.json").read_text(encoding="utf-8")
    )
    store = DataStore(output)
    now = datetime(2026, 10, 16, 0, 5, tzinfo=UTC)
    datasets = []
    observations: list[Observation] = []
    for case in fixture["rest"]:
        request = MarketRequest.model_validate(case["request"])
        payload = case["response"]
        meta = Provenance(
            source="KIS_OFFICIAL_SCHEMA_SYNTHETIC",
            endpoint=request.path,
            tr_id=request.tr_id,
            symbol=request.symbol,
            venue=request.venue,
            session="REGULAR",
            request_time=now,
            received_at=now,
            acquired_at=now,
            source_hash=digest(canonical(scrub(payload))),
            ingestion_run_id="fixture-v1",
            request_fingerprint=content_hash(request.model_dump(mode="json")),
            data_origin="SYNTHETIC_FIXTURE",
        )

        def acquire_fixture(
            payload: dict[str, Any] = payload, meta: Provenance = meta
        ) -> tuple[dict[str, Any], Provenance]:
            return payload, meta

        dataset, rows = collect_rest(
            store, "fixture:" + request.operation, request, acquire_fixture
        )
        datasets.append(dataset)
        observations.extend(rows)
    for frame in fixture["stream"]:
        parts = frame.split("|", 3)
        payload = dict(zip(WS_COLUMNS[parts[1]], parts[3].split("^"), strict=True))
        rows = parse_frame(frame, now, session="REGULAR", data_origin="SYNTHETIC_FIXTURE")
        meta = Provenance(
            source="KIS_OFFICIAL_SCHEMA_SYNTHETIC",
            endpoint="websocket-market-data",
            tr_id=parts[1],
            symbol=rows[0].symbol,
            venue="KRX",
            session="REGULAR",
            request_time=now,
            received_at=now,
            acquired_at=now,
            source_hash=digest(canonical(payload)),
            ingestion_run_id="fixture-v1",
            data_origin="SYNTHETIC_FIXTURE",
        )
        identity = "fixture:" + parts[1]
        store.put_raw(identity, payload, meta)
        dataset = store.put_dataset(rows, identity)
        datasets.append(dataset)
        observations.extend(store.load_dataset(dataset))
    disclosures = []
    registry = DisclosureRegistry()
    for row in fixture["dart"]:
        parsed = parse_disclosure(
            row,
            now,
            datetime(2026, 10, 16, tzinfo=UTC),
            "SYNTHETIC_CALENDAR_NEXT_SESSION",
            row.get("supersedes_receipt"),
        )
        registry.add(parsed)
        meta = Provenance(
            source="OPENDART_SCHEMA_SYNTHETIC",
            endpoint="/api/list.json",
            tr_id="DART_LIST",
            symbol=parsed.stock_code or "000000",
            venue="KRX",
            session="UNKNOWN",
            request_time=now,
            received_at=now,
            acquired_at=now,
            source_hash=digest(canonical(scrub(row))),
            ingestion_run_id="fixture-v1",
            data_origin="SYNTHETIC_FIXTURE",
        )
        store.put_raw("fixture:dart:" + parsed.rcept_no, row, meta)
        disclosures.append(parsed.model_dump(mode="json"))
    immutable_write(output / "public_events.json", canonical(disclosures))
    economics = [
        EconomicSource(category=category, unit="UNVERIFIED", version="unverified-v1").model_dump(
            mode="json"
        )
        for category in (
            "COMMISSION",
            "TAX",
            "SPREAD",
            "LIQUIDITY",
            "LOT_SIZE",
            "BUYING_POWER",
            "SETTLED_CASH",
            "RECEIVABLES",
            "PAYABLES",
            "CASH_INTEREST",
            "SERVER_COST",
            "DATA_COST",
            "SERVICE_COST",
        )
    ]
    immutable_write(output / "economic_sources.json", canonical(economics))
    entry = AvailabilityEntry(
        source="KIS_SCHEMA_FIXTURE",
        symbols=tuple(sorted({r.symbol for r in observations})),
        obtained_start=min(r.exchange_date for r in observations),
        obtained_end=max(r.exchange_date for r in observations),
        resolution="DAILY/MINUTE/SECOND",
        venues=("KRX",),
        sessions=("REGULAR",),
        observed_unique=len(observations),
        missing_rate=None,
        valid_observation_days=len(
            {r.exchange_date for r in observations if r.complete and not r.quality_flags}
        ),
        actual_lag_seconds=tuple(
            (r.received_at - r.event_time).total_seconds()
            for r in observations
            if r.event_time and r.received_at >= r.event_time
        ),
        data_origin="SYNTHETIC_FIXTURE",
        pit_reconstructable=False,
        license_ref="SELF_AUTHORED_SYNTHETIC_FIXTURE_NO_MARKET_DATA_LICENSE_CLAIM",
    )
    matrix = build_matrix((entry,), now)
    immutable_write(output / "DATA_AVAILABILITY_MATRIX.json", canonical(matrix))
    result = {
        "scope": "SYNTHETIC_FIXTURE_ONLY",
        "dataset_ids": sorted(datasets),
        "rows": len(observations),
        "public_events": len(disclosures),
        "normalized_hash": content_hash(
            sorted((r.model_dump(mode="json") for r in observations), key=lambda r: r["record_id"])
        ),
        "status": "KM001_ADAPTER_READY_DATA_HOLD",
        "strategies": matrix["strategies"],
        "actual_market_rows": 0,
        "order_calls": 0,
        "cancel_calls": 0,
    }
    immutable_write(output / "run_summary.json", canonical(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="K-MAST read-only market data; all orders blocked")
    parser.add_argument("mode", choices=("fixture", "read"), nargs="?", default="fixture")
    parser.add_argument("--output", type=Path, default=Path("data/km001"))
    parser.add_argument("--allow-network-readonly", action="store_true")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--symbol", default="005930")
    parser.add_argument(
        "--operation",
        choices=("daily", "minute_today", "minute_history", "price", "quote", "index"),
        default="daily",
    )
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--at", type=local_time.fromisoformat)
    parser.add_argument("--interval-seconds", type=float)
    parser.add_argument("--max-requests", type=int, default=5)
    args = parser.parse_args()
    if args.mode == "fixture":
        print(json.dumps(fixture_run(args.output), indent=2))
        return
    if (
        not args.allow_network_readonly
        or args.credentials_file is None
        or args.interval_seconds is None
    ):
        parser.error(
            "read requires explicit network flag, local credential file, and pacing interval"
        )
    try:
        config = BrokerConfig.model_validate_json(args.credentials_file.read_bytes())
        policy = NetworkPolicy(
            allow_network_readonly=True, symbols=(args.symbol,), max_requests=args.max_requests
        )
        permit = NetworkPermit(policy)
        clock = SystemClock()
        wire = Wire(permit)
        auth = KISAuth(wire, clock)
        client = MarketClient(
            config,
            wire,
            TokenManager(config, auth, clock),
            AccountRateLimiter(time.monotonic),
            RatePolicy(
                interval_seconds=args.interval_seconds,
                evidence_ref="USER_SELECTED_PACING_NOT_GUARANTEED_QUOTA",
            ),
            clock,
        )
        request = MarketRequest(
            operation=args.operation, symbol=args.symbol, start=args.start, end=args.end, at=args.at
        )
        store = DataStore(args.output)
        identity = "user-collection:" + content_hash(request.model_dump(mode="json"))
        secrets = tuple(
            s.get_secret_value()
            for s in (config.app_key, config.app_secret, config.account_ref)
            if s
        )

        def acquire() -> tuple[dict[str, Any], Provenance]:
            before = clock.now()
            reply = client.read(request)
            received = clock.now()
            meta = Provenance(
                source="KIS",
                endpoint=request.path,
                tr_id=request.tr_id,
                symbol=request.symbol,
                venue=request.venue,
                session="UNKNOWN",
                request_time=before,
                received_at=received,
                acquired_at=received,
                source_hash=digest(canonical(scrub(reply.body, secrets))),
                ingestion_run_id=content_hash([identity, before.isoformat()]),
                request_fingerprint=content_hash(request.model_dump(mode="json")),
                data_origin="KIS_READONLY",
            )
            return reply.body, meta

        dataset, rows = collect_rest(store, identity, request, acquire, secrets)
        print(
            json.dumps(
                {
                    "dataset_id": dataset,
                    "rows": len(rows),
                    "status": "DATA_HOLD_PENDING_QA",
                    "order_calls": 0,
                    "cancel_calls": 0,
                }
            )
        )
    except Exception:
        parser.exit(1, "collection failed closed; raw errors and credential inputs suppressed\n")


if __name__ == "__main__":
    main()
