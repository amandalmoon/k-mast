"""Explicitly approved PAPER EWY quotation collection; no trading capability."""

import argparse
import hashlib
import http.client
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from kmast.data.store import DataStore, digest, immutable_write
from scripts.read_kis_env import load_env

ROOT = Path("data/data-first-private-df004-ewy")
ROUTE = "/uapi/overseas-price/v1/quotations/dailyprice"
START, END = date(2025, 10, 17), date(2026, 10, 16)


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    temporary.replace(path)


def validate(method, route, params):
    if method == "POST" and route == "/oauth2/tokenP":
        if set(params) != {"grant_type", "appkey", "appsecret"}:
            raise PermissionError("AUTH_SCOPE")
        return
    if method != "GET" or route != ROUTE:
        raise PermissionError("CAPABILITY_DENIED")
    if set(params) != {"AUTH", "EXCD", "SYMB", "GUBN", "BYMD", "MODP"}:
        raise PermissionError("PARAMETER_SCOPE")
    if (
        params["AUTH"] != ""
        or params["EXCD"] not in {"NYS", "AMS"}
        or params["SYMB"] != "EWY"
        or params["GUBN"] != "0"
        or params["MODP"] not in {"0", "1"}
        or not START <= datetime.strptime(params["BYMD"], "%Y%m%d").date() <= END
    ):
        raise PermissionError("QUOTATION_SCOPE")


def cached(state, params):
    for event in reversed(state["events"]):
        if all(
            event.get(k) == v
            for k, v in (
                ("exchange_code", params["EXCD"]),
                ("modp", params["MODP"]),
                ("cursor", params["BYMD"]),
            )
        ):
            raw = (ROOT / (event["sha256"] + ".json")).read_bytes()
            if digest(raw) != event["sha256"]:
                raise ValueError("CACHE_HASH_MISMATCH")
            return json.loads(raw)
    return None


def collect():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-approved-paper-readonly", action="store_true")
    parser.add_argument("--capture-wire-evidence", action="store_true")
    args = parser.parse_args()
    if not args.allow_approved_paper_readonly:
        parser.error("explicit approval opt-in required")
    config = load_env(Path.home() / ".kmast-readonly/.env")
    if config.environment.value != "PAPER":
        raise PermissionError("PAPER_REQUIRED_NO_LIVE_FALLBACK")
    ROOT.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "budget.json"
    state = (
        json.loads(state_path.read_bytes())
        if state_path.exists()
        else {"requests": 0, "auth": 0, "last_request_epoch": 0, "events": []}
    )
    if not args.capture_wire_evidence:
        # A complete previous traversal is immutable price evidence; reuse without auth.
        covered = []
        for event in state["events"]:
            if event.get("exchange_code") == "AMS" and event.get("modp") == "0":
                values = cached(state, {"EXCD": "AMS", "MODP": "0", "BYMD": event["cursor"]})
                covered.extend(r["xymd"] for r in values)
        if (
            covered
            and min(covered) <= START.strftime("%Y%m%d")
            and max(covered) >= END.strftime("%Y%m%d")
        ):
            print(
                json.dumps(
                    {
                        "status": "CACHED_PRICE_ROWS_NO_NETWORK",
                        "requests": state["requests"],
                        "auth": state["auth"],
                    }
                )
            )
            return
    token = ""
    secrets = [config.app_key.get_secret_value(), config.app_secret.get_secret_value()]

    def send(method, route, params):
        validate(method, route, params)
        auth = method == "POST"
        if not auth and not args.capture_wire_evidence:
            saved = cached(state, params)
            if saved is not None:
                return saved
        if state["requests"] >= 12 or (auth and state["auth"] >= 2):
            raise PermissionError("APPROVED_BUDGET_EXHAUSTED")
        # Wait from previous RESPONSE completion, with scheduling/clock margin.
        time.sleep(max(0, 3.05 - (time.time() - state["last_request_epoch"])))
        state["requests"] += 1
        state["auth"] += int(auth)
        state["last_request_epoch"] = time.time()
        write(state_path, state)  # consume before I/O, including failures and resumes
        headers = {"content-type": "application/json; charset=utf-8"}
        if not auth:
            headers.update(
                {
                    "authorization": "Bearer " + token,
                    "appkey": secrets[0],
                    "appsecret": secrets[1],
                    "tr_id": "HHDFS76240000",
                    "custtype": "P",
                }
            )
        conn = http.client.HTTPSConnection("openapivts.koreainvestment.com", 29443, timeout=20)
        before = datetime.now(UTC).isoformat()
        try:
            conn.request(
                method,
                route if auth else route + "?" + urlencode(params),
                body=json.dumps(params).encode() if auth else None,
                headers=headers,
            )
            response = conn.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("SIZE")
            body = json.loads(raw) if response.status == 200 else {}
            if not isinstance(body, dict):
                raise ValueError("SHAPE")
            event = {
                "sequence": state["requests"],
                "kind": "AUTH" if auth else "EWY_DAILY",
                "http_status": response.status,
                "request_time": before,
                "received_at": datetime.now(UTC).isoformat(),
            }
            if not auth:
                if any(secret.encode() in raw for secret in secrets if secret):
                    raise ValueError("SENSITIVE_RESPONSE")
                # Foreign metadata is deliberately separate from domestic Provenance.
                wire_hash = digest(raw)
                store = DataStore(ROOT)
                wire_path = store.raw_path("DF004_EWY_WIRE_SHA256:" + wire_hash)
                immutable_write(wire_path, raw)
                event.update(
                    wire_sha256=wire_hash, wire_path=str(wire_path.relative_to(ROOT.resolve()))
                )
                # No request credentials/remote messages are persisted. Price fields only.
                rows = body.get("output2", [])
                fields = {"xymd", "open", "high", "low", "clos", "tvol"}
                rows = (
                    [
                        {k: v for k, v in row.items() if k in fields}
                        for row in rows
                        if isinstance(row, dict)
                    ]
                    if isinstance(rows, list)
                    else []
                )
                payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
                if any(secret.encode() in payload for secret in secrets if secret):
                    raise ValueError("SENSITIVE_RESPONSE")
                sha = hashlib.sha256(payload).hexdigest()
                target = ROOT / (sha + ".json")
                if not target.exists():
                    target.write_bytes(payload)
                elif target.read_bytes() != payload:
                    raise ValueError("HASH_CONFLICT")
                event.update(
                    {
                        "exchange_code": params["EXCD"],
                        "modp": params["MODP"],
                        "cursor": params["BYMD"],
                        "rows": len(rows),
                        "sha256": sha,
                        "storage": "SANITIZED_PRICE_FIELDS_NOT_WIRE_BYTES",
                        "outcome": "OBSERVED_ROWS" if rows else "NO_USABLE_ROWS",
                    }
                )
                state["events"].append(event)
                write(state_path, state)
                return rows
            state["events"].append(event)
            write(state_path, state)
            return body
        except Exception:
            state["events"].append(
                {"sequence": state["requests"], "outcome": "IO_OR_RESPONSE_FAILED"}
            )
            write(state_path, state)
            raise RuntimeError("BOUNDED_COLLECTION_FAILED_INPUTS_SUPPRESSED") from None
        finally:
            conn.close()
            state["last_request_epoch"] = time.time()
            write(state_path, state)

    try:
        body = send(
            "POST",
            "/oauth2/tokenP",
            {"grant_type": "client_credentials", "appkey": secrets[0], "appsecret": secrets[1]},
        )
        token = body.get("access_token", "")
        if not token:
            raise RuntimeError("PAPER_AUTH_UNAVAILABLE")
        secrets.append(token)
        for exchange in ("AMS", "NYS"):
            if args.capture_wire_evidence and exchange == "NYS":
                continue
            cursor = END
            for page in range(3):
                params = {
                    "AUTH": "",
                    "EXCD": exchange,
                    "SYMB": "EWY",
                    "GUBN": "0",
                    "BYMD": cursor.strftime("%Y%m%d"),
                    "MODP": "0",
                }
                rows = send("GET", ROUTE, params)
                if page == 0 and not args.capture_wire_evidence:
                    send("GET", ROUTE, {**params, "MODP": "1"})
                if not rows:
                    break
                oldest = min(datetime.strptime(r["xymd"], "%Y%m%d").date() for r in rows)
                if oldest <= START:
                    break
                next_cursor = oldest - timedelta(days=1)
                if next_cursor >= cursor:
                    raise RuntimeError("PAGINATION_NO_PROGRESS")
                cursor = max(START, next_cursor)
    except Exception:
        state["status"] = "DATA_BLOCKED_PAPER_NO_LIVE_FALLBACK"
    else:
        state["status"] = "COLLECTION_COMPLETE_REQUIRES_VALIDATION"
    write(state_path, state)
    print(json.dumps({k: state[k] for k in ("status", "requests", "auth")}, indent=2))


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "collection.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        collect()
    finally:
        os.close(descriptor)
        lock.unlink()


if __name__ == "__main__":
    main()
