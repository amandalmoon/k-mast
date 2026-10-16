"""Explicit, bounded market-only check using a human-specified local .env; never echo inputs."""

import argparse
import json
import time
from datetime import timedelta
from pathlib import Path

from kmast.brokers.kis.adapter import AccountRateLimiter, RatePolicy, TokenManager
from kmast.brokers.kis.network import KISAuth, MarketClient, NetworkPermit, NetworkPolicy, Wire
from kmast.brokers.kis.requests import MarketRequest
from kmast.core.clock import SystemClock
from kmast.core.config import BrokerConfig
from kmast.data.models import KST, Provenance
from kmast.data.normalization import content_hash
from kmast.data.pipeline import collect_rest
from kmast.data.store import DataStore, canonical, digest, scrub


def load_env(path: Path) -> BrokerConfig:
    try:
        values = {}
        allowed = {
            "KIS_ENVIRONMENT",
            "KIS_APP_KEY",
            "KIS_APP_SECRET",
            "KMAST_MODE",
            "KMAST_ORDER_ENABLED",
            "KMAST_LIVE_ENABLED",
        }
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            name, value = name.strip(), value.strip()
            if not separator or name not in allowed or name in values:
                raise ValueError
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[name] = value
        if (
            values.get("KMAST_MODE") != "RESEARCH"
            or values.get("KMAST_ORDER_ENABLED") != "false"
            or values.get("KMAST_LIVE_ENABLED") != "false"
            or not values.get("KIS_APP_KEY")
            or not values.get("KIS_APP_SECRET")
        ):
            raise ValueError
        environment = values["KIS_ENVIRONMENT"]
        if environment not in {"LIVE", "PAPER"}:
            raise ValueError
        return BrokerConfig(
            environment=environment,
            credential_environment=environment,
            account_environment=environment,
            account_ref="READONLY_MARKET_ALIAS",
            endpoint="https://openapi.koreainvestment.com:9443"
            if environment == "LIVE"
            else "https://openapivts.koreainvestment.com:29443",
            app_key=values["KIS_APP_KEY"],
            app_secret=values["KIS_APP_SECRET"],
        )
    except Exception:
        raise ValueError("local credential configuration invalid; inputs suppressed") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".kmast-readonly/.env")
    parser.add_argument("--allow-network-readonly", action="store_true")
    args = parser.parse_args()
    if not args.allow_network_readonly:
        parser.error("explicit read-only network opt-in required")
    clock = SystemClock()
    now = clock.now()
    output = Path("data") / ("km003-readonly-" + now.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    permit = NetworkPermit(
        NetworkPolicy(
            allow_network_readonly=True,
            symbols=("005930",),
            max_requests=3,
            max_days=7,
            max_attempts=1,
            timeout_seconds=10,
        )
    )
    counts = {
        "authentication_attempts": 0,
        "market_query_attempts": 0,
        "order_calls": 0,
        "cancel_calls": 0,
        "account_queries": 0,
    }

    class AuditedWire(Wire):
        def send(self, config, method, path, headers, payload):
            if method == "POST" and path == "/oauth2/tokenP":
                counts["authentication_attempts"] += 1
            elif method == "GET" and path.startswith("/uapi/domestic-stock/v1/quotations/"):
                counts["market_query_attempts"] += 1
            else:
                raise PermissionError("capability outside this market-only check")
            result = super().send(config, method, path, headers, payload)
            counts["last_http_status"] = result.status
            return result

    summary = {
        "checked_at": now.isoformat(),
        "scope": "ONE_SYMBOL_SEVEN_CALENDAR_DAYS",
        "status": "READ_CHECK_HOLD",
        "data_status": "DATA_BLOCKED",
        "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
        "live_status": "LIVE_NOT_APPROVED",
    }
    try:
        config = load_env(args.env_file)
        wire = AuditedWire(permit)
        client = MarketClient(
            config,
            wire,
            TokenManager(config, KISAuth(wire, clock), clock),
            AccountRateLimiter(time.monotonic),
            RatePolicy(interval_seconds=3, evidence_ref="CONSERVATIVE_CHECK_NOT_VERIFIED_QUOTA"),
            clock,
        )
        end = now.astimezone(KST).date() - timedelta(days=1)
        request = MarketRequest(
            operation="daily", symbol="005930", start=end - timedelta(days=6), end=end
        )
        secrets = tuple(
            secret.get_secret_value()
            for secret in (config.app_key, config.app_secret, config.account_ref)
            if secret
        )

        def acquire():
            before = clock.now()
            reply = client.read(request)
            received = clock.now()
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
                ingestion_run_id=content_hash(
                    [before.isoformat(), request.model_dump(mode="json")]
                ),
                request_fingerprint=content_hash(request.model_dump(mode="json")),
                data_origin="KIS_READONLY",
            )

        dataset, rows = collect_rest(
            DataStore(output), "bounded-daily-check", request, acquire, secrets
        )
        summary.update(
            {
                "status": "READ_CHECK_OK_DATA_HOLD",
                "real_rows": len(rows),
                "requested_start": str(request.start),
                "requested_end": str(request.end),
                "observed_start": str(min(r.exchange_date for r in rows)) if rows else None,
                "observed_end": str(max(r.exchange_date for r in rows)) if rows else None,
                "dataset_id": dataset,
                "quality_flags": sorted({flag for row in rows for flag in row.quality_flags}),
                "blockers": [
                    "PIT_RELEASE_EVIDENCE",
                    "PIT_UNIVERSE_AND_DELISTINGS",
                    "CORPORATE_ACTIONS",
                    "BENCHMARK_HISTORY",
                    "CALENDAR_AND_COVERAGE",
                    "REAL_COSTS",
                    "DATA_USAGE_RIGHTS",
                ],
            }
        )
    except Exception:
        summary["reason"] = "CHECK_FAILED_CLOSED_NO_RAW_ERRORS_OR_SECRET_INPUTS_LOGGED"
    summary.update(counts)
    summary["network_requests_used"] = permit.used
    (output / "read-check.json").write_bytes((json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps(summary, indent=2))
    print("Local ignored evidence folder:", output.as_posix())
    raise SystemExit(0 if summary["status"] == "READ_CHECK_OK_DATA_HOLD" else 1)


if __name__ == "__main__":
    main()
