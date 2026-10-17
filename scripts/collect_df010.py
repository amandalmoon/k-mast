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
    atomic_json,
    immutable_write,
    process_lock,
)
from kmast.data.parsers import parse_rest
from kmast.data.pilot_acquisition import PilotWire
from kmast.data.store import canonical, digest
from scripts.read_kis_env import load_env

FOLDER = Path("data/data-first-private-df010-prices")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved-paper", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_paper:
        parser.error("DF010 separate explicit user approval required")
    protocol_bytes = Path("artifacts/df010/DF010_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    cache = json.loads(Path("artifacts/df010/cache-audit.json").read_bytes())
    if not cache["indices_complete"]:
        raise RuntimeError("INDEX_CACHE_NOT_QUALIFIED_REVIEW_REQUIRED")
    symbols = tuple(t["symbol"] for t in protocol["targets"])
    config = load_env(Path.home() / ".kmast-readonly/.env")
    clock = SystemClock()
    with process_lock(FOLDER / "process.lock"):
        wire = PilotWire(FOLDER, symbols, enabled=True)
        tokens = TokenManager(config, KISAuth(wire, clock), clock)
        store = AtomicPanelStore(FOLDER)
        manifest_path = FOLDER / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_bytes())
            if manifest_path.exists()
            else {
                "protocol_sha256": digest(protocol_bytes),
                "pages": {},
                "histories": {},
                "account_calls": 0,
                "order_calls": 0,
                "cancel_calls": 0,
                "live_authentication": 0,
            }
        )
        assert manifest["protocol_sha256"] == digest(protocol_bytes)

        def page(request):
            identity = "DF010_V1:" + content_hash(request.model_dump(mode="json"))
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

        for target in protocol["targets"]:
            start, end = (date.fromisoformat(target[k]) for k in ("start", "end"))
            for basis in ("RAW", "ADJUSTED"):
                cursor = end
                for _ in range(2):
                    rows = query(target["symbol"], "daily", start, cursor, basis)
                    if not rows:
                        break
                    earliest = min(r.exchange_date for r in rows)
                    if earliest <= start + timedelta(days=7):
                        break
                    next_cursor = earliest - timedelta(days=1)
                    if next_cursor >= cursor:
                        raise RuntimeError("PAGINATION_NO_PROGRESS")
                    cursor = next_cursor
                print(
                    json.dumps(
                        {
                            "symbol": target["symbol"],
                            "basis": basis,
                            "requests": wire.state["requests"],
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    main()
