"""Immutable DF017 request reservations, bounded private responses and retention plans."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kmast.data.https_bar_gate import START, STORE
from kmast.data.panel_acquisition import immutable_write
from kmast.data.store import canonical, digest

BODY_CAP = 1024 * 1024
RAW_CAP = 128 * 1024 * 1024
TOTAL_CAP = 256 * 1024 * 1024
PEAK_RESERVE = 8 * BODY_CAP


class Journal:
    """Use under process_lock. Pending reservations remain spent across any restart."""

    def __init__(self, root: Path, binding: dict[str, Any]):
        self.root = root
        if binding["origin"] not in {"SYNTHETIC", "OBSERVED"}:
            raise PermissionError("ISOLATED_ORIGIN_REQUIRED")
        if binding["origin"] == "OBSERVED" and root.resolve() != STORE.absolute():
            raise PermissionError("EXACT_PRIVATE_PILOT_ROOT_REQUIRED")
        if root.exists() and any(
            p.name
            not in {"binding.json", "process.lock", "reservations", "outcomes", "raw", "normalized"}
            for p in root.iterdir()
        ):
            raise ValueError("ISOLATED_NEW_PILOT_STORE_REQUIRED")
        immutable_write(root / "binding.json", canonical(binding))
        self.binding = binding
        self.reservations: list[dict[str, Any]] = []
        self.outcomes: dict[int, dict[str, Any]] = {}
        self.verify()

    def verify(self) -> None:
        if any(
            p.is_symlink() or not p.resolve().is_relative_to(self.root.resolve())
            for p in self.root.rglob("*")
        ):
            raise ValueError("PILOT_STORE_PATH_ESCAPE")
        if (self.root / "binding.json").read_bytes() != canonical(self.binding):
            raise ValueError("STORE_BINDING_CONFLICT")
        if any(self.root.rglob("*.tmp")):
            raise ValueError("INTERRUPTED_ATOMIC_PUBLICATION_HOLD")
        previous = "GENESIS"
        self.reservations = []
        for p in sorted((self.root / "reservations").glob("*.json")):
            raw, expected = p.read_bytes(), len(self.reservations) + 1
            r = json.loads(raw)
            ordinal = r.get("ordinal")
            if (
                type(ordinal) is not int
                or not 0 <= ordinal <= 22
                or r.get("attempt") != 1 + sum(q["ordinal"] == ordinal for q in self.reservations)
            ):
                raise ValueError("RESERVATION_SCOPE_CONFLICT")
            if (
                p.name != f"{expected:03}-{digest(raw)}.json"
                or r["id"] != expected
                or r["previous"] != previous
            ):
                raise ValueError("RESERVATION_CHAIN_CONFLICT")
            self.reservations.append(r)
            previous = digest(raw)
        self.outcomes = {}
        raw_names: set[str] = set()
        normalized_names: set[str] = set()
        for p in sorted((self.root / "outcomes").glob("*.json")):
            raw = p.read_bytes()
            r = json.loads(raw)
            i = r["id"]
            if (
                i in self.outcomes
                or not 1 <= i <= len(self.reservations)
                or p.name != f"{i:03}-{digest(raw)}.json"
            ):
                raise ValueError("OUTCOME_IDENTITY_CONFLICT")
            self.outcomes[i] = r
            for folder, key, names in (
                ("raw", "raw_sha256", raw_names),
                ("normalized", "normalized_sha256", normalized_names),
            ):
                h = r.get(key)
                if h is not None:
                    if not isinstance(h, str) or not re.fullmatch(r"[a-f0-9]{64}", h):
                        raise ValueError("RESPONSE_HASH_IDENTITY_REQUIRED")
                    name = h + ".bin"
                    content = (self.root / folder / name).read_bytes()
                    if digest(content) != h:
                        raise ValueError("RESPONSE_LINEAGE_HASH_CONFLICT")
                    if folder == "raw" and r.get("captured_sha256") != h:
                        raise ValueError("CAPTURE_RAW_LINEAGE_CONFLICT")
                    if folder == "normalized" and json.loads(content).get("source_sha256") != r.get(
                        "captured_sha256"
                    ):
                        raise ValueError("NORMALIZED_SOURCE_LINEAGE_CONFLICT")
                    names.add(name)
        for folder, names in (("raw", raw_names), ("normalized", normalized_names)):
            if {p.name for p in (self.root / folder).glob("*")} != names:
                raise ValueError("ORPHAN_RESPONSE_BYTES_HOLD")
        if len(self.reservations) > 45 or sum(r["ordinal"] == 0 for r in self.reservations) > 1:
            raise ValueError("PERSISTENT_BUDGET_CORRUPT")
        for ordinal in range(1, 23):
            if sum(r["ordinal"] == ordinal for r in self.reservations) > 2:
                raise ValueError("PERSISTENT_QUERY_BUDGET_CORRUPT")
        if self.bytes_used() > TOTAL_CAP or self.raw_used() > RAW_CAP:
            raise PermissionError("EXISTING_STORE_OVER_CAP")

    def bytes_used(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    def raw_used(self) -> int:
        return sum(p.stat().st_size for p in (self.root / "raw").glob("*.bin"))

    def reserve(self, ordinal: int, now: datetime) -> int:
        if not 0 <= ordinal <= 22 or len(self.reservations) >= 45:
            raise PermissionError("TOTAL_REQUEST_BUDGET_EXHAUSTED")
        if any(r["id"] not in self.outcomes for r in self.reservations):
            raise PermissionError("UNRESOLVED_ATTEMPT_HOLD_NO_REFUND")
        n = sum(r["ordinal"] == ordinal for r in self.reservations)
        if n >= (1 if ordinal == 0 else 2):
            raise PermissionError("AUTH_OR_QUERY_ATTEMPTS_EXHAUSTED")
        if ordinal > 0:
            if not self.reservations or self.reservations[0]["ordinal"] != 0:
                raise PermissionError("AUTH_FIRST_REQUIRED")
            terminal = {
                self.reservations[i - 1]["ordinal"]
                for i, r in self.outcomes.items()
                if r["terminal"]
            }
            expected = next((i for i in range(1, 23) if i not in terminal), 23)
            if ordinal != expected:
                raise PermissionError("FROZEN_QUERY_ORDER_REQUIRED")
        if self.bytes_used() + PEAK_RESERVE > TOTAL_CAP or self.raw_used() + BODY_CAP + 1 > RAW_CAP:
            raise PermissionError("STORAGE_RESERVATION_DENIED_BEFORE_IO")
        i = len(self.reservations) + 1
        prev = "GENESIS" if not self.reservations else digest(canonical(self.reservations[-1]))
        record = dict(
            id=i,
            ordinal=ordinal,
            attempt=n + 1,
            previous=prev,
            reserved_at=now.isoformat(),
            raw_reserved=BODY_CAP,
            total_reserved=PEAK_RESERVE,
        )
        raw = canonical(record)
        immutable_write(self.root / "reservations" / f"{i:03}-{digest(raw)}.json", raw)
        self.reservations.append(record)
        return i

    def finish(
        self, i: int, metadata: dict[str, Any], raw: bytes | None, normalized: dict[str, Any] | None
    ) -> None:
        if i in self.outcomes or not 1 <= i <= len(self.reservations):
            raise ValueError("RESERVATION_REQUIRED_FOR_RESPONSE")
        if raw is not None and len(raw) > BODY_CAP + 1:
            raise PermissionError("BODY_CAPTURE_CAP")
        norm = canonical(normalized) if normalized is not None else None
        if norm is not None and len(norm) > 2 * BODY_CAP:
            raise PermissionError("NORMALIZED_RECORD_CAP")
        for folder, payload in (("raw", raw), ("normalized", norm)):
            if payload is not None:
                immutable_write(self.root / folder / (digest(payload) + ".bin"), payload)
        record = dict(
            metadata,
            id=i,
            origin=self.binding["origin"],
            raw_sha256=digest(raw) if raw is not None else None,
            normalized_sha256=digest(norm) if norm is not None else None,
        )
        payload = canonical(record)
        if len(payload) > 65536:
            raise PermissionError("OUTCOME_METADATA_CAP")
        immutable_write(self.root / "outcomes" / f"{i:03}-{digest(payload)}.json", payload)
        self.outcomes[i] = record

    def retention_plan(self, now: datetime) -> dict[str, Any]:
        self.verify()
        first = (
            datetime.fromisoformat(self.reservations[0]["reserved_at"])
            if self.reservations
            else START
        )
        expires = first + timedelta(days=30)
        if now.tzinfo is None:
            raise PermissionError("AWARE_RETENTION_CLOCK_REQUIRED")
        files = {
            p.relative_to(self.root).as_posix(): digest(p.read_bytes())
            for p in self.root.rglob("*")
            if p.is_file() and p.name != "process.lock"
        }
        return dict(
            expires_at=expires.isoformat(),
            expired=now >= expires,
            files=files,
            hash_retention_allowed=self.binding["hash_retention_allowed"],
        )

    def purge_expired(self, now: datetime, approved_plan: dict[str, Any]) -> None:
        plan = self.retention_plan(now)
        if plan != approved_plan or not plan["expired"] or not plan["hash_retention_allowed"]:
            raise PermissionError("EXPLICIT_VERIFIED_EXPIRED_PURGE_PLAN_REQUIRED")
        expected = STORE.absolute()
        if self.binding["origin"] == "OBSERVED" and self.root.resolve() != expected:
            raise PermissionError("EXACT_PILOT_PURGE_ROOT_REQUIRED")
        # No recursive deletion. Validate the complete manifest before unlinking.
        targets = [self.root / name for name in plan["files"]]
        if any(
            p.is_symlink() or not p.resolve().is_relative_to(self.root.resolve()) for p in targets
        ):
            raise PermissionError("RETENTION_PATH_ESCAPE")
        for p in targets:
            p.unlink()
