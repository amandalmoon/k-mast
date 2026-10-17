"""Approved 8-symbol, 1-year, 48-request market-only acquisition with durable resume."""

import argparse
import io
import json
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from datetime import time as local_time
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

STOCKS = ("005930", "000660", "035420", "247540", "086520", "028300")
START, END = date(2025, 10, 17), date(2026, 10, 16)


class Budget:
    def __init__(self, path):
        self.path = path
        self.state = (
            json.loads(path.read_bytes())
            if path.exists()
            else dict(used=0, auth=0, market=0, master=0)
        )
        self.last = 0.0

    def consume(self, category):
        if self.state["used"] >= 48:
            raise PermissionError("approved global request budget exhausted")
        time.sleep(max(0, 3 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.state["used"] += 1
        self.state[category] += 1
        self.path.write_bytes(canonical(self.state))


class MarketOnlyWire(Wire):
    def __init__(self, permit, budget):
        super().__init__(permit)
        self.budget = budget

    def send(self, config, method, path, headers, payload):
        category = "auth" if method == "POST" and path == "/oauth2/tokenP" else "market"
        allowed = {"daily", "index_daily", "minute_today", "price", "quote"}
        from kmast.brokers.kis.requests import ROUTES

        paths = {"/uapi/domestic-stock/v1/quotations/" + ROUTES[op][0] for op in allowed}
        if not (category == "auth" or method == "GET" and path in paths):
            raise PermissionError("outside approved market-only scope")
        self.budget.consume(category)
        return super().send(config, method, path, headers, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("explicit --execute required; default network OFF")
    folder = Path("data/data-first-private-market-v1")
    folder.mkdir(parents=True, exist_ok=True)
    proof = Path("artifacts/data-first")
    budget = Budget(folder / "request-budget.json")
    clock = SystemClock()
    config = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = tuple(
        s.get_secret_value() for s in (config.app_key, config.app_secret, config.account_ref) if s
    )
    store = DataStore(folder)
    records = []
    errors = []
    token_manager = None
    masters = []
    for market, tail in (("kospi", 228), ("kosdaq", 222)):
        path = folder / (market + "_code.mst.zip")
        try:
            if not path.exists():
                budget.consume("master")
                url = f"https://new.real.download.dws.co.kr/common/master/{market}_code.mst.zip"
                with urllib.request.urlopen(url, timeout=20) as response:
                    payload = response.read(16_000_001)
                if len(payload) > 16_000_000:
                    raise ValueError("master size limit")
                path.write_bytes(payload)
            body = path.read_bytes()
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                item = archive.getinfo(market + "_code.mst")
                if item.file_size > 32_000_000:
                    raise ValueError("uncompressed master size limit")
                text = archive.read(item).decode("cp949")
            entries = []
            for line in text.splitlines(keepends=True):
                head = line[:-tail]
                if len(head) >= 21:
                    entries.append(
                        dict(
                            symbol=head[:9].strip(), isin=head[9:21].strip(), name=head[21:].strip()
                        )
                    )
            (folder / (market + "-master.json")).write_bytes(canonical(entries))
            masters.append(
                dict(
                    market=market,
                    row_count=len(entries),
                    sha256=digest(body),
                    approved_symbols_present=sorted(
                        e["symbol"] for e in entries if e["symbol"] in STOCKS
                    ),
                    scope="CURRENT_SNAPSHOT_NOT_HISTORICAL_UNIVERSE",
                )
            )
        except Exception as error:
            errors.append(dict(operation="master", market=market, category=type(error).__name__))

    def client_for(symbol, index):
        nonlocal token_manager
        permit = NetworkPermit(
            NetworkPolicy(
                allow_network_readonly=True,
                symbols=(symbol, index),
                max_requests=48,
                max_days=366,
                max_attempts=2,
                backoff_seconds=3,
            )
        )
        wire = MarketOnlyWire(permit, budget)
        if token_manager is None:
            token_manager = TokenManager(config, KISAuth(wire, clock), clock)
        return MarketClient(
            config,
            wire,
            token_manager,
            AccountRateLimiter(time.monotonic),
            RatePolicy(interval_seconds=3, evidence_ref="USER_APPROVED_GLOBAL_PACING"),
            clock,
        )

    def collect(client, request):
        fingerprint = request.model_dump(mode="json")
        identity = "DATA_FIRST_V1:" + content_hash(
            [fingerprint, str(clock.now().astimezone(KST).date())]
            if request.operation == "minute_today"
            else fingerprint
        )

        def acquire():
            before = clock.now()
            reply = client.read(request)
            now = clock.now()
            return reply.body, Provenance(
                source="KIS",
                endpoint=request.path,
                tr_id=request.tr_id,
                symbol=request.symbol,
                venue=request.venue,
                session="UNKNOWN",
                request_time=before,
                received_at=now,
                acquired_at=now,
                source_hash=digest(canonical(scrub(reply.body, secrets))),
                ingestion_run_id=content_hash([identity, before.isoformat()]),
                request_fingerprint=content_hash(request.model_dump(mode="json")),
                data_origin="KIS_READONLY",
            )

        dataset, rows = collect_rest(store, identity, request, acquire, secrets)
        records.append(
            dict(
                dataset_id=dataset,
                operation=request.operation,
                symbol=request.symbol,
                price_basis=request.price_basis,
                rows=len(rows),
                start=min((str(r.exchange_date) for r in rows), default=None),
                end=max((str(r.exchange_date) for r in rows), default=None),
                flags=sorted({f for r in rows for f in r.quality_flags}),
            )
        )
        return rows

    def history(symbol, operation, basis="RAW"):
        client = client_for(
            symbol if operation == "daily" else "005930", "0001" if len(symbol) == 6 else symbol
        )
        cursor = END
        for _ in range(8):
            rows = collect(
                client,
                MarketRequest(
                    operation=operation, symbol=symbol, start=START, end=cursor, price_basis=basis
                ),
            )
            if not rows:
                return
            earliest = min(r.exchange_date for r in rows)
            if earliest <= START:
                return
            next_cursor = earliest - timedelta(days=1)
            if next_cursor >= cursor:
                raise ValueError("non-progressing date pagination")
            cursor = next_cursor

    for symbol, operation, basis in [
        *((s, "daily", "RAW") for s in STOCKS),
        ("0001", "index_daily", "RAW"),
        ("1001", "index_daily", "RAW"),
        ("005930", "daily", "ADJUSTED"),
    ]:
        try:
            history(symbol, operation, basis)
        except Exception as error:
            errors.append(
                dict(
                    operation=operation,
                    symbol=symbol,
                    price_basis=basis,
                    category=type(error).__name__,
                )
            )
    client = client_for("005930", "0001")
    current_local = clock.now().astimezone(KST)
    minute_cursor = min(local_time(15, 30), local_time(current_local.hour, 0))
    probes = (
        MarketRequest(operation="minute_today", symbol="005930", at=minute_cursor),
        MarketRequest(operation="price", symbol="005930"),
    )
    for request in probes:
        try:
            collect(client, request)
        except Exception as error:
            errors.append(
                dict(
                    operation=request.operation,
                    symbol=request.symbol,
                    category=type(error).__name__,
                )
            )
    result = dict(
        scope="EXPLORATORY_REAL_DATA",
        environment=config.environment.value,
        approval=dict(
            symbols=STOCKS + ("0001", "1001"),
            start=str(START),
            end=str(END),
            maximum_total_requests=48,
            minimum_request_spacing_seconds=3,
        ),
        private_store=folder.as_posix(),
        datasets=records,
        masters=masters,
        errors=errors,
        network=budget.state,
        account_queries=0,
        order_calls=0,
        cancel_calls=0,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    (folder / "collection.json").write_bytes(canonical(result))
    (proof / "collection.json").write_bytes(canonical(result))
    assert all(
        all(secret.encode() not in p.read_bytes() for secret in secrets)
        for p in folder.rglob("*")
        if p.is_file()
    )
    print(
        json.dumps(
            dict(
                requests=budget.state,
                datasets=len(records),
                rows=sum(r["rows"] for r in records),
                masters=masters,
                errors=errors,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
