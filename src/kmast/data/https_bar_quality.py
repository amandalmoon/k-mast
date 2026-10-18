"""Private schema/observation diagnostics. Unknown semantics never clear research gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from kmast.data.bar_orb import Receipt, Session, parse_bars, parse_quote
from kmast.data.https_bar_gate import START
from kmast.data.store import digest

if TYPE_CHECKING:
    from kmast.data.https_bar_collector import Clock, Reply
    from kmast.data.https_bar_store import Journal


def diagnose(reply: Reply, call: dict[str, Any], origin: str, clock: Clock) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        source_sha256=digest(reply.raw),
        ordinal=call["ordinal"],
        symbol=call["symbol"],
        tr_id=call["tr_id"],
        origin=origin,
        fields={},
        rows=[],
        schema_ok=False,
        parser_error=None,
        flags=[
            "FIRST_TRADE_UNKNOWN",
            "MARKET_STATE_UNKNOWN",
            "CORRECTION_COVERAGE_UNKNOWN",
            "CLOCK_BOUND_UNKNOWN",
        ],
        quality=dict(
            SOURCE_OK=None,
            SCHEMA_OK=None,
            TEMPORAL_OK=None,
            MARKET_OK=None,
            CORRECTION_OK=None,
            ORB5_OK=None,
            ORB15_OK=None,
            POST_SIGNAL_QUOTE_OK=None,
        ),
        execution_verified=False,
        rvol="RVOL_NOT_READY",
        profit=None,
    )
    try:
        data = json.loads(reply.raw)
        if not isinstance(data, dict) or data.get("rt_cd") != "0":
            raise ValueError
        if origin == "OBSERVED":
            result["quality"].update(
                SOURCE_OK=reply.tls_verified and reply.status == 200,
                TEMPORAL_OK=False,
                MARKET_OK=False,
                CORRECTION_OK=False,
                ORB5_OK=False,
                ORB15_OK=False,
                POST_SIGNAL_QUOTE_OK=False,
            )
        opening = START.replace(hour=9, minute=0)
        session = Session(opening.date(), opening, opening.replace(hour=15, minute=30))
        query = reply.request_at
        if "FID_INPUT_HOUR_1" in call["parameters"]:
            query = datetime.strptime(
                "20261020" + call["parameters"]["FID_INPUT_HOUR_1"], "%Y%m%d%H%M%S"
            ).replace(tzinfo=opening.tzinfo)
        rec = Receipt(
            call["symbol"],
            call["tr_id"],
            reply.request_at,
            reply.response_at,
            clock.now(),
            query,
            "OBSERVED" if origin == "OBSERVED" else "SYNTHETIC",
        )
        for name in ("output1", "output2"):
            block = data.get(name)
            rows = block if isinstance(block, list) else [block]
            fields = sorted(
                {
                    k
                    for r in rows
                    if isinstance(r, dict)
                    for k in r
                    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", k)
                }
            )
            result["fields"][name] = fields
        if call["tr_id"] == "FHKST03010200":
            bars = parse_bars(reply.raw, rec, session)
            result["rows"] = [
                dict(
                    label_at=b.label_at.isoformat() if b.label_at else None,
                    start=None,
                    end=None,
                    open=str(b.open),
                    high=str(b.high),
                    low=str(b.low),
                    close=str(b.close),
                    volume=str(b.volume),
                    flags=list(b.flags),
                    available_at=b.available_at.isoformat(),
                    source_sha256=b.response_sha256,
                )
                for b in bars
            ]
            result["schema_ok"] = all(b.label_at is not None for b in bars)
            result["flags"] = sorted({f for b in bars for f in b.flags})
        elif call["tr_id"] == "FHKST01010200":
            q = parse_quote(reply.raw, rec, session)
            required = {"aspr_acpt_hour", "bidp1", "askp1", "bidp_rsqn1", "askp_rsqn1"}
            result["schema_ok"] = required <= set(result["fields"]["output1"])
            result["rows"] = [
                dict(
                    bid=str(q.bid),
                    ask=str(q.ask),
                    flags=list(q.flags),
                    provider_at=q.provider_at.isoformat() if q.provider_at else None,
                    date_basis=q.date_basis,
                    is_fill=False,
                )
            ]
            result["flags"] = list(q.flags)
        else:
            rows = data["output2"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
                raise ValueError
            for row in rows:
                if not re.fullmatch(r"[0-9]{6}", str(row["stck_cntg_hour"])):
                    raise ValueError
                datetime.strptime(row["stck_cntg_hour"], "%H%M%S")
                for field in ("stck_prpr", "cnqn", "acml_vol", "askp", "bidp"):
                    value = Decimal(str(row[field]))
                    if not value.is_finite() or value < 0:
                        raise ValueError
            result["rows"] = [
                dict(
                    stck_cntg_hour=r["stck_cntg_hour"],
                    stck_prpr=r["stck_prpr"],
                    cnqn=r["cnqn"],
                    acml_vol=r["acml_vol"],
                    source_date=None,
                )
                for r in rows
            ]
            result["schema_ok"] = True
        if origin == "OBSERVED":
            result["quality"].update(
                SOURCE_OK=reply.tls_verified and reply.status == 200,
                SCHEMA_OK=result["schema_ok"],
                TEMPORAL_OK=False,
                MARKET_OK=False,
                CORRECTION_OK=False,
                ORB5_OK=False,
                ORB15_OK=False,
                POST_SIGNAL_QUOTE_OK=False,
            )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        result["parser_error"] = "SCHEMA_OR_FIELD_SEMANTICS_HOLD"
        if origin == "OBSERVED":
            result["quality"]["SCHEMA_OK"] = False
    # Validation completes after every parsing/diagnostic operation, not before.
    result["validation_complete_at"] = clock.now().isoformat()
    for normalized_row in result["rows"]:
        if "available_at" in normalized_row:
            normalized_row["available_at"] = result["validation_complete_at"]
    return result


def requery_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Private as-observed changes, never infer correction finality from unchanged values."""
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    changes = []
    for record in records:
        if record["tr_id"] != "FHKST03010200":
            continue
        for row in record["rows"]:
            label = row.get("label_at")
            if label is None:
                continue
            key = (record["symbol"], label)
            if key in previous:
                before = previous[key]
                changed = [
                    k for k in ("open", "high", "low", "close", "volume") if before[k] != row[k]
                ]
                changes.append(
                    dict(
                        symbol=key[0],
                        label_at=label,
                        changed_fields=changed,
                        before_sha256=before["source_sha256"],
                        after_sha256=row["source_sha256"],
                        correction_finality_verified=False,
                    )
                )
            previous[key] = row
    return changes


def audit_store(journal: Journal) -> dict[str, Any]:
    """Private observation audit. Raw values/timelines never go to public stdout."""
    journal.verify()
    records = []
    delays = []
    status: Counter[str] = Counter()
    for i, outcome in sorted(journal.outcomes.items()):
        status[str(outcome.get("status"))] += 1
        h = outcome.get("normalized_sha256")
        if h:
            records.append(json.loads((journal.root / "normalized" / (h + ".bin")).read_bytes()))
        if outcome.get("request_at") and outcome.get("response_at"):
            start = datetime.fromisoformat(outcome["request_at"])
            end = datetime.fromisoformat(outcome["response_at"])
            valid = datetime.fromisoformat(outcome["validation_complete_at"])
            delays.append(
                dict(
                    id=i,
                    request_at=start.isoformat(),
                    response_at=end.isoformat(),
                    validation_at=valid.isoformat(),
                    http_seconds=(end - start).total_seconds(),
                    validation_seconds=(valid - end).total_seconds(),
                )
            )
    fields: dict[str, set[str]] = {}
    row_counts: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    labels: list[str] = []
    for r in records:
        fields.setdefault(r["tr_id"], set()).update(
            k for group in r["fields"].values() for k in group
        )
        row_counts[r["tr_id"]] += len(r["rows"])
        flags.update(r["flags"])
        labels.extend(row["label_at"] for row in r["rows"] if row.get("label_at"))
    return dict(
        quality_counts={
            k: {
                str(value): sum(r["quality"][k] is value for r in records)
                for value in (True, False, None)
            }
            for k in (
                "SOURCE_OK",
                "SCHEMA_OK",
                "TEMPORAL_OK",
                "MARKET_OK",
                "CORRECTION_OK",
                "ORB5_OK",
                "ORB15_OK",
                "POST_SIGNAL_QUOTE_OK",
            )
        },
        origin=journal.binding["origin"],
        attempts=len(journal.reservations),
        auth_attempts=sum(r["ordinal"] == 0 for r in journal.reservations),
        market_attempts=sum(r["ordinal"] > 0 for r in journal.reservations),
        retry_attempts=sum(r["attempt"] > 1 for r in journal.reservations),
        unresolved_attempts=len(journal.reservations) - len(journal.outcomes),
        failed_attempts=sum(
            not r.get("successful_response", False) for r in journal.outcomes.values()
        ),
        http_status_counts=dict(status),
        fields={k: sorted(v) for k, v in fields.items()},
        rows=dict(row_counts),
        delays=delays,
        source_flags=dict(flags),
        first_bar_label=min(labels) if labels else None,
        last_bar_label=max(labels) if labels else None,
        same_bar_changes=requery_changes(records),
        completed_bars_qualified=0,
        semantics_unknown_rows=sum(
            len(r["rows"]) for r in records if r["tr_id"] == "FHKST03010200"
        ),
        raw_normalized_hashes=[
            dict(id=i, raw=r.get("raw_sha256"), normalized=r.get("normalized_sha256"))
            for i, r in sorted(journal.outcomes.items())
        ],
        raw_bytes=journal.raw_used(),
        total_bytes=journal.bytes_used(),
        independent_qualification=False,
    )
