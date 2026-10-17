"""Approved DF005 PAPER panel acquisition; immutable cache, bounded probes then history."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from kmast.brokers.kis.adapter import TokenManager
from kmast.brokers.kis.network import KISAuth
from kmast.brokers.kis.requests import MarketRequest
from kmast.core.clock import SystemClock
from kmast.data.models import Provenance
from kmast.data.normalization import content_hash
from kmast.data.panel_acquisition import (
    AtomicPanelStore,
    PanelWire,
    atomic_json,
    immutable_write,
    process_lock,
)
from kmast.data.parsers import parse_rest
from kmast.data.store import canonical, digest
from scripts.read_kis_env import load_env

FOLDER = Path("data/data-first-private-df005-panel")
START, END = date(2022, 9, 1), date(2025, 10, 16)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved-paper", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_paper:
        parser.error("explicit user-approved PAPER opt-in required")
    protocol_bytes = Path("artifacts/df005/DF005_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    seal = json.loads(Path("artifacts/df005/protocol-seal.json").read_bytes())
    assert digest(protocol_bytes) == seal["protocol_sha256"]
    symbols = tuple(protocol["kospi"] + protocol["kosdaq"])
    config = load_env(Path.home() / ".kmast-readonly/.env")
    clock = SystemClock()
    with process_lock(FOLDER / "process.lock"):
        wire = PanelWire(FOLDER, symbols, enabled=True)
        if args.probe_only:
            wire.session_limit = 12
        tokens = TokenManager(config, KISAuth(wire, clock), clock)
        store = AtomicPanelStore(FOLDER)
        manifest_path = FOLDER / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_bytes())
            if manifest_path.exists()
            else {
                "protocol_sha256": seal["protocol_sha256"],
                "pages": {},
                "histories": {},
                "authentication_approved": True,
                "order_calls": 0,
                "cancel_calls": 0,
                "account_calls": 0,
                "live_authentication": 0,
            }
        )
        assert manifest["protocol_sha256"] == seal["protocol_sha256"]

        def page(request):
            identity = "DF005_V1:" + content_hash(request.model_dump(mode="json"))
            saved = store.cached(identity)
            if saved is None:
                token = tokens.get()
                headers = {
                    "content-type": "application/json; charset=utf-8",
                    "authorization": "Bearer " + token.value.get_secret_value(),
                    "appkey": config.app_key.get_secret_value(),
                    "appsecret": config.app_secret.get_secret_value(),
                    "tr_id": request.tr_id,
                    "custtype": "P",
                }
                reply = wire.send(config, "GET", request.path, headers, request.params())
                e = wire.last_event
                if reply.status != 200 or reply.body.get("rt_cd") != "0":
                    raise RuntimeError("PROVIDER_RESPONSE_UNAVAILABLE")
                meta = Provenance(
                    source="KIS",
                    endpoint=request.path,
                    tr_id=request.tr_id,
                    symbol=request.symbol,
                    venue="KRX",
                    session="UNKNOWN",
                    request_time=e["request_time"],
                    received_at=e["received_at"],
                    acquired_at=e["received_at"],
                    source_hash=digest(canonical(reply.body)),
                    ingestion_run_id=content_hash([identity, e["received_at"]]),
                    request_fingerprint=content_hash(request.model_dump(mode="json")),
                    data_origin="KIS_READONLY",
                )
                saved = store.put_raw(identity, reply.body, meta)
                immutable_write(
                    FOLDER / "lineage" / (content_hash(identity) + ".json"), canonical(e)
                )
            meta = Provenance.model_validate(saved["metadata"])
            rows = parse_rest(saved["payload"], request, meta)
            dataset = store.put_dataset(rows, identity)
            verified = store.load_dataset(dataset)
            manifest["pages"][identity] = dict(
                request=request.model_dump(mode="json"),
                dataset_id=dataset,
                rows=len(verified),
                source_hash=meta.source_hash,
                normalized_hash=digest(canonical([r.model_dump(mode="json") for r in verified])),
                record_hashes={
                    r.record_id: digest(canonical(r.model_dump(mode="json"))) for r in verified
                },
            )
            atomic_json(manifest_path, manifest)
            return verified

        def query(symbol, op, start, end, basis="RAW"):
            return page(
                MarketRequest(operation=op, symbol=symbol, start=start, end=end, price_basis=basis)
            )

        probes = {}
        for symbol in (protocol["kospi"][0], protocol["kosdaq"][0]):
            for a, b in ((START, date(2022, 12, 30)), (date(2025, 7, 1), END)):
                for basis in ("RAW", "ADJUSTED"):
                    rows = query(symbol, "daily", a, b, basis)
                    probes[symbol + str(a) + basis] = len(rows)
        for idx in ("0001", "1001"):
            probes[idx] = len(query(idx, "index_daily", START, date(2022, 12, 30)))
        manifest["probes"] = probes
        atomic_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "stage": "PROBE",
                    "nonempty": sum(v > 0 for v in probes.values()),
                    "total": len(probes),
                    "requests": wire.state["requests"],
                }
            ),
            flush=True,
        )
        if args.probe_only or not all(probes.values()):
            return
        # Indices first provide the observed session calendar. No invented missing sessions.
        plan = [(idx, "index_daily", "RAW") for idx in ("0001", "1001")]
        plan += [(s, "daily", basis) for s in symbols for basis in ("RAW", "ADJUSTED")]
        for symbol, op, basis in plan:
            cursor, total = END, 0
            status = "PAGE_LIMIT_REACHED"
            observed_start = None
            for _ in range(20):
                try:
                    rows = query(symbol, op, START, cursor, basis)
                except PermissionError:
                    raise
                except Exception:
                    status = "PROVIDER_OR_NORMALIZATION_HOLD"
                    break
                total += len(rows)
                if not rows:
                    status = "EMPTY_OR_HISTORY_EXHAUSTED"
                    break
                earliest = min(r.exchange_date for r in rows)
                observed_start = str(earliest)
                if earliest <= START:
                    status = "START_REACHED"
                    break
                next_cursor = earliest - timedelta(days=1)
                if next_cursor >= cursor:
                    status = "PAGINATION_NO_PROGRESS_HOLD"
                    break
                cursor = next_cursor
            manifest["histories"][symbol + ":" + basis] = dict(
                symbol=symbol,
                operation=op,
                basis=basis,
                rows=total,
                observed_start=observed_start,
                status=status,
            )
            atomic_json(manifest_path, manifest)
            print(
                json.dumps(
                    {
                        "completed_histories": len(manifest["histories"]),
                        "target_histories": len(plan),
                        "requests": wire.state["requests"],
                        "last_status": status,
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
