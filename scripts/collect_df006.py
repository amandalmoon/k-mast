"""Explicitly approved OpenDART-only collection. Never prints request URLs or secrets."""

import argparse
import calendar
import http.client
import io
import json
import re
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from kmast.data.panel_acquisition import atomic_json, immutable_write, process_lock
from kmast.data.store import canonical, digest

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/data-first-private-df006-events"
PROTOCOL_SHA = "60900915a3e65dd5f03e9b4f21a792d2fa0ace76"


def load_key(path):
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            if "=" not in line:
                raise ValueError("INVALID_LOCAL_KEY_FILE")
            name, value = line.split("=", 1)
            if name.strip() != "OPENDART_API_KEY":
                raise ValueError("UNEXPECTED_LOCAL_KEY_FIELD")
            values.append(value.strip().strip('"').strip("'"))
    if len(values) != 1 or not re.fullmatch(r"[a-zA-Z0-9]{40}", values[0]):
        raise ValueError("INVALID_LOCAL_KEY_FORMAT")
    return values[0]


def months():
    start, last = date(2022, 10, 17), date(2025, 10, 8)
    while start <= last:
        end = min(
            last, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        )
        yield start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        start = end + timedelta(days=1)


class DartWire:
    def __init__(self, folder, key, enabled=False):
        self.folder, self.key, self.enabled = folder, key, enabled
        folder.mkdir(parents=True, exist_ok=True)
        self.budget_path = folder / "budget.json"
        self.budget = (
            json.loads(self.budget_path.read_bytes())
            if self.budget_path.exists()
            else {"used": 0, "maximum": 600, "events": []}
        )
        if self.budget["maximum"] != 600 or self.budget["used"] > 600:
            raise ValueError("BUDGET_CONFLICT")
        # Even an interrupted in-flight request cannot cause an immediate restart request.
        self.ready = time.perf_counter() + (3.10 if self.budget["used"] else 0)

    def get(self, path, params):
        validate_request(path, params)
        identity = digest(canonical({"path": path, "params": params}))
        cache = self.folder / "cache" / (identity + ".json")
        if cache.exists():
            record = json.loads(cache.read_bytes())
            if (
                record["identity"] != identity
                or record["path"] != path
                or record["params"] != params
            ):
                raise ValueError("CACHE_IDENTITY_CONFLICT")
            raw = (self.folder / "wire" / (record["sha256"] + ".bin")).read_bytes()
            if digest(raw) != record["sha256"]:
                raise ValueError("CACHE_HASH_CONFLICT")
            matching = [e for e in self.budget["events"] if e["number"] == record["request_number"]]
            if not matching or matching[0].get("sha256") != record["sha256"]:
                raise ValueError("CACHE_BUDGET_LINEAGE_CONFLICT")
            return raw, record
        if not self.enabled:
            raise ValueError("EXPLICIT_APPROVAL_REQUIRED")
        prior_attempts = [e for e in self.budget["events"] if e["identity"] == identity]
        # Recover the crash window after a completed response but before cache publication.
        for event in reversed(prior_attempts):
            if event.get("http_status") == 200 and "completed_at" in event and "sha256" in event:
                wire_file = self.folder / "wire" / (event["sha256"] + ".bin")
                if not wire_file.exists():
                    continue
                raw = wire_file.read_bytes()
                if digest(raw) != event["sha256"] or self.key.encode() in raw:
                    raise ValueError("RECOVERY_INTEGRITY_CONFLICT")
                valid = (
                    json.loads(raw).get("status") in {"000", "013"}
                    if path.endswith("list.json")
                    else zipfile.is_zipfile(io.BytesIO(raw))
                )
                if valid:
                    record = {
                        "identity": identity,
                        "sha256": event["sha256"],
                        "acquired_at": event["completed_at"],
                        "request_number": event["number"],
                        "path": path,
                        "params": params,
                    }
                    immutable_write(cache, canonical(record))
                    return raw, record
        if len(prior_attempts) >= 2:
            raise ValueError("REQUEST_RETRY_BUDGET_EXHAUSTED")
        for attempt in range(len(prior_attempts), 2):
            if self.budget["used"] >= 600:
                raise ValueError("REQUEST_BUDGET_EXHAUSTED")
            # Windows monotonic() can have ~15.6ms resolution. Recheck the
            # high-resolution performance clock after every early wake.
            while True:
                remaining_wait = self.ready - time.perf_counter()
                if remaining_wait <= 0:
                    break
                time.sleep(remaining_wait)
            self.budget["used"] += 1
            event = {
                "number": self.budget["used"],
                "identity": identity,
                "path": path,
                "attempt": attempt,
                "started_at": datetime.now(UTC).isoformat(),
                "outcome": "RESERVED_UNKNOWN_RESPONSE",
            }
            self.budget["events"].append(event)
            atomic_json(self.budget_path, self.budget)
            connection = http.client.HTTPSConnection("opendart.fss.or.kr", timeout=45)
            failed = False
            try:
                query = urlencode(params | {"crtfc_key": self.key})
                connection.request("GET", path + "?" + query, headers={"User-Agent": "KMAST-DF006"})
                response = connection.getresponse()
                raw = response.read(32 * 1024 * 1024 + 1)
                event["http_status"] = response.status
                event["sha256"] = digest(raw)
                event["bytes"] = len(raw)
                if len(raw) > 32 * 1024 * 1024:
                    raise ValueError("RESPONSE_SIZE_LIMIT")
                if self.key.encode() in raw:
                    raise ValueError("SENSITIVE_RESPONSE_WITHHELD")
                immutable_write(self.folder / "wire" / (event["sha256"] + ".bin"), raw)
                event["outcome"] = "RECEIVED"
                failed = response.status >= 500
            except (OSError, http.client.HTTPException):
                event["outcome"] = "TRANSPORT_FAILURE"
                failed = True
                raw = None
            finally:
                connection.close()
                event["completed_at"] = datetime.now(UTC).isoformat()
                self.ready = time.perf_counter() + 3.10
                atomic_json(self.budget_path, self.budget)
            if failed:
                if attempt == 0:
                    continue
                raise ValueError("TRANSPORT_RETRY_EXHAUSTED")
            if event["http_status"] != 200:
                raise ValueError("HTTP_FAILURE")
            if raw is None:
                raise ValueError("NO_RESPONSE")
            if path.endswith("list.json"):
                status = json.loads(raw).get("status")
                event["api_status"] = status
                atomic_json(self.budget_path, self.budget)
                if status not in {"000", "013"}:
                    raise ValueError("DART_API_STATUS_" + str(status))
            elif not zipfile.is_zipfile(io.BytesIO(raw)):
                # Failure bytes are already retained; never print their content/message.
                raise ValueError("DOCUMENT_NOT_ZIP")
            record = {
                "identity": identity,
                "sha256": event["sha256"],
                "acquired_at": event["completed_at"],
                "request_number": event["number"],
                "path": path,
                "params": params,
            }
            immutable_write(cache, canonical(record))
            return raw, record
        raise ValueError("UNREACHABLE")


def validate_request(path, params):
    if path == "/api/list.json":
        if set(params) != {
            "bgn_de",
            "end_de",
            "pblntf_detail_ty",
            "last_reprt_at",
            "page_count",
            "page_no",
            "sort",
            "sort_mth",
        }:
            raise ValueError("REQUEST_SCHEMA_BLOCKED")
        if (
            params["pblntf_detail_ty"] != "B001"
            or params["last_reprt_at"] != "N"
            or params["page_count"] != "100"
            or params["sort"] != "date"
            or params["sort_mth"] != "asc"
            or not str(params["page_no"]).isdigit()
            or not 1 <= int(params["page_no"]) <= 600
            or (params["bgn_de"], params["end_de"]) not in set(months())
        ):
            raise ValueError("REQUEST_SCOPE_BLOCKED")
    elif path == "/api/document.xml":
        if set(params) != {"rcept_no"} or not re.fullmatch(r"[0-9]{14}", params["rcept_no"]):
            raise ValueError("DOCUMENT_SCOPE_BLOCKED")
    else:
        raise ValueError("ENDPOINT_BLOCKED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error("explicit approved opt-in required")
    protocol = ROOT / "artifacts/df006/DF006_PROTOCOL.json"
    import subprocess

    frozen = subprocess.check_output(
        ["git", "show", PROTOCOL_SHA + ":artifacts/df006/DF006_PROTOCOL.json"], cwd=ROOT
    )
    if frozen != protocol.read_bytes():
        raise ValueError("FROZEN_PROTOCOL_CHANGED")
    selection = json.loads((ROOT / "artifacts/df005/DF005_PROTOCOL.json").read_bytes())
    symbols = set(selection["kospi"] + selection["kosdaq"])
    key = load_key(Path.home() / ".kmast-readonly/opendart.env")
    with process_lock(FOLDER / "process.lock"):
        wire = DartWire(FOLDER, key, enabled=True)
        rows = {}
        manifest_path = FOLDER / "manifest.json"
        manifest = {
            "protocol_sha256": digest(frozen),
            "protocol_commit": PROTOCOL_SHA,
            "pages": {},
            "documents": {},
            "complete": False,
        }
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_bytes())
            if manifest["protocol_sha256"] != digest(frozen):
                raise ValueError("MANIFEST_PROTOCOL_CONFLICT")
        for begin, end in months():
            page, pages = 1, 1
            while page <= pages:
                raw, record = wire.get(
                    "/api/list.json",
                    {
                        "bgn_de": begin,
                        "end_de": end,
                        "pblntf_detail_ty": "B001",
                        "last_reprt_at": "N",
                        "page_count": "100",
                        "page_no": str(page),
                        "sort": "date",
                        "sort_mth": "asc",
                    },
                )
                body = json.loads(raw)
                pages = int(body.get("total_page", 0))
                if pages > 600:
                    raise ValueError("PAGINATION_EXCEEDS_BUDGET")
                manifest["pages"][begin + ":" + str(page)] = record
                for row in body.get("list", []):
                    if row.get("stock_code") not in symbols:
                        continue
                    receipt = row["rcept_no"]
                    normalized = {
                        "row": row,
                        "raw_response_sha256": record["sha256"],
                        "acquired_at": record["acquired_at"],
                    }
                    old = rows.get(receipt)
                    if old is not None and old["row"] != row:
                        raise ValueError("CONFLICTING_LIST_RECEIPT")
                    rows[receipt] = normalized
                atomic_json(
                    FOLDER / "selected-disclosures.json",
                    {"rows": rows, "normalized_sha256": digest(canonical(rows))},
                )
                atomic_json(manifest_path, manifest)
                if args.probe_only:
                    print(
                        json.dumps(
                            {
                                "probe": "PASS",
                                "requests": wire.budget["used"],
                                "first_month_pages": pages,
                                "selected_rows": len(rows),
                            }
                        ),
                        flush=True,
                    )
                    return
                page += 1
            print(
                json.dumps(
                    {
                        "completed_month": begin[:6],
                        "requests": wire.budget["used"],
                        "selected_rows": len(rows),
                    }
                ),
                flush=True,
            )
        # Fetch only selected acquisition-decision originals and their titled corrections.
        for receipt, value in sorted(rows.items()):
            title = "".join(value["row"]["report_nm"].split())
            if "자기주식취득결정" not in title:
                continue
            raw, record = wire.get("/api/document.xml", {"rcept_no": receipt})
            # Read ZIP members in memory; never extract or execute embedded code.
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
                    raise ValueError("DOCUMENT_EXPANSION_LIMIT")
                for name in archive.namelist():
                    member = archive.read(name)
                    if key.encode() in member:
                        raise ValueError("SENSITIVE_DOCUMENT_WITHHELD")
            manifest["documents"][receipt] = record
            atomic_json(manifest_path, manifest)
        manifest["complete"] = True
        manifest["selected_rows"] = len(rows)
        atomic_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "collection": "COMPLETE",
                    "requests": wire.budget["used"],
                    "selected_rows": len(rows),
                    "candidate_documents": len(manifest["documents"]),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Error categories only: no potentially credential-bearing exception or URL repr.
        category = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if not re.fullmatch(r"[A-Z_0-9]+", category):
            category = type(exc).__name__
        print("DF006_COLLECTION_STOPPED:" + category, flush=True)
        raise SystemExit(1) from None
