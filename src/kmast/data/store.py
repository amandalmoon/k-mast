import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from kmast.data.models import Observation, Provenance
from kmast.data.normalization import content_hash

SENSITIVE = re.compile(
    r"^(access_token|refresh_token|token|appsecret|app_secret|secret|secretkey|appkey|app_key|"
    r"authorization|approval_key|account|account_number|account_ref|cano|hts_id|crtfc_key|"
    r"cookie|set-cookie)$",
    re.I,
)


def scrub(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            k: scrub(v, secrets)
            for k, v in value.items()
            if not SENSITIVE.search(str(k)) and str(k) not in {"msg1", "message", "msg"}
        }
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def immutable_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != value:
            raise ValueError("immutable content conflict") from None
        return
    with os.fdopen(descriptor, "wb") as file:
        file.write(value)
        file.flush()
        os.fsync(file.fileno())


class DataStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def raw_path(self, identity: str) -> Path:
        return self.root / "raw" / (content_hash(identity) + ".json")

    def cached(self, identity: str) -> dict[str, Any] | None:
        path = self.raw_path(identity)
        if not path.exists():
            return None
        result: dict[str, Any] = json.loads(path.read_bytes())
        if digest(canonical(result["payload"])) != result["metadata"]["source_hash"]:
            raise ValueError("raw storage corruption")
        Provenance.model_validate(result["metadata"])
        return result

    def put_raw(
        self,
        identity: str,
        payload: dict[str, Any],
        metadata: Provenance,
        secrets: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        safe = scrub(payload, secrets)
        if digest(canonical(safe)) != metadata.source_hash:
            raise ValueError("sanitized source hash mismatch")
        record = {"payload": safe, "metadata": metadata.model_dump(mode="json")}
        existing = self.cached(identity)
        if existing:
            if existing["metadata"]["source_hash"] == metadata.source_hash:
                return existing
            quarantine = (
                self.root
                / "quarantine"
                / (content_hash([identity, metadata.source_hash]) + ".json")
            )
            immutable_write(quarantine, canonical(record))
            raise ValueError("raw identity conflict quarantined")
        immutable_write(self.raw_path(identity), canonical(record))
        return record

    def put_dataset(self, records: tuple[Observation, ...], raw_identity: str) -> str:
        records = tuple(sorted(records, key=lambda r: r.record_id))
        raw = self.cached(raw_identity)
        if raw is None:
            raise ValueError("raw provenance missing")
        rows = sorted((r.model_dump(mode="json") for r in records), key=lambda r: r["record_id"])
        if len({r["record_id"] for r in rows}) != len(rows):
            raise ValueError("duplicate normalized identity")
        if any(r.source_hash != raw["metadata"]["source_hash"] for r in records):
            raise ValueError("normalized/raw lineage mismatch")
        dataset_id = content_hash(rows)
        folder = self.root / "normalized" / dataset_id
        if (folder / "manifest.json").exists():
            self.load_dataset(dataset_id)
            return dataset_id
        # Canonical JSON preserves exact contracts; typed columns support Parquet filtering.
        table = pa.table(
            {
                "record_id": pa.array([r.record_id for r in records], type=pa.string()),
                "kind": pa.array([r.kind for r in records], type=pa.string()),
                "symbol": pa.array([r.symbol for r in records], type=pa.string()),
                "venue": pa.array([r.venue for r in records], type=pa.string()),
                "available_at": pa.array(
                    [r.available_at for r in records], type=pa.timestamp("us", tz="UTC")
                ),
                "close_krw": pa.array([r.close for r in records], type=pa.decimal128(28, 8)),
                "volume_shares": pa.array([r.volume for r in records], type=pa.decimal128(28, 8)),
                "payload_json": pa.array(
                    [canonical(r.model_dump(mode="json")).decode("utf-8") for r in records],
                    type=pa.string(),
                ),
            }
        )
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", version="2.6")
        parquet = sink.getvalue().to_pybytes()
        manifest = {
            "dataset_id": dataset_id,
            "row_count": len(rows),
            "raw_identity": raw_identity,
            "source_hash": raw["metadata"]["source_hash"],
            "parquet_sha256": digest(parquet),
            "format_version": "km001-parquet-v1",
            "parser_versions": sorted({r.parser_version for r in records}),
            "data_origins": sorted({r.data_origin for r in records}),
            "obtained_start": min((r.exchange_date.isoformat() for r in records), default=None),
            "obtained_end": max((r.exchange_date.isoformat() for r in records), default=None),
            "quality_flags": sorted({flag for r in records for flag in r.quality_flags}),
            "complete_rows": sum(r.complete for r in records),
            "missing_rate": None,
            "coverage_note": "EXPECTED_GRID_UNVERIFIED",
        }
        immutable_write(folder / "observations.parquet", parquet)
        immutable_write(folder / "manifest.json", canonical(manifest))
        return dataset_id

    def load_dataset(self, dataset_id: str) -> tuple[Observation, ...]:
        if not re.fullmatch("[a-f0-9]{64}", dataset_id):
            raise ValueError("invalid dataset id")
        folder = self.root / "normalized" / dataset_id
        manifest = json.loads((folder / "manifest.json").read_bytes())
        payload = (folder / "observations.parquet").read_bytes()
        if digest(payload) != manifest["parquet_sha256"]:
            raise ValueError("parquet corruption")
        table = pq.read_table(pa.BufferReader(payload))
        records = tuple(
            Observation.model_validate_json(row) for row in table["payload_json"].to_pylist()
        )
        rows = sorted((r.model_dump(mode="json") for r in records), key=lambda r: r["record_id"])
        raw = self.cached(manifest["raw_identity"])
        if (
            content_hash(rows) != dataset_id
            or len(rows) != manifest["row_count"]
            or raw is None
            or raw["metadata"]["source_hash"] != manifest["source_hash"]
            or any(r.source_hash != manifest["source_hash"] for r in records)
        ):
            raise ValueError("dataset manifest/lineage mismatch")
        return tuple(sorted(records, key=lambda r: r.record_id))
