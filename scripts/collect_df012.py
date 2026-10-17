"""DF012 explicitly approved PAPER collection of eleven frozen historical pages."""

import argparse
import json
from datetime import date
from pathlib import Path

from kmast.brokers.kis.adapter import TokenManager
from kmast.brokers.kis.network import KISAuth
from kmast.brokers.kis.requests import MarketRequest
from kmast.core.clock import SystemClock
from kmast.data.five_event_acquisition import ExpansionWire
from kmast.data.models import Provenance
from kmast.data.normalization import content_hash
from kmast.data.panel_acquisition import (
    AtomicPanelStore,
    atomic_json,
    immutable_write,
    process_lock,
)
from kmast.data.parsers import parse_rest
from kmast.data.store import canonical, digest
from scripts.read_kis_env import load_env

FOLDER = Path("data/data-first-private-df012-prices")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved-paper", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_paper:
        parser.error("DF012 separate explicit user approval required")
    protocol_bytes = Path("artifacts/df012/DF012_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    cache = json.loads(Path("artifacts/df012/cache-audit.json").read_bytes())
    if not cache["prior_cache_unchanged"]:
        raise RuntimeError("PRIOR_CACHE_HASH_CONFLICT")
    symbols = tuple(t["historical_short_code"] for t in protocol["targets"])
    config = load_env(Path.home() / ".kmast-readonly/.env")
    clock = SystemClock()
    with process_lock(FOLDER / "process.lock"):
        wire = ExpansionWire(FOLDER, symbols, enabled=True)
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
            identity = "DF012_V1:" + content_hash(request.model_dump(mode="json"))
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

        # Sole missing index page first; other index dates are verified cache reuse.
        for item in sorted(protocol["requests"], key=lambda q: q["operation"] != "index_daily"):
            rows = query(
                item["symbol"],
                item["operation"],
                date.fromisoformat(item["start"]),
                date.fromisoformat(item["end"]),
                item["basis"],
            )
            print(
                json.dumps(
                    {
                        "symbol": item["symbol"],
                        "basis": item["basis"],
                        "rows": len(rows),
                        "requests": wire.state["requests"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
