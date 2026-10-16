from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from kmast.brokers.kis.requests import MarketRequest
from kmast.data.models import KST, Observation, Provenance, observation_id, utc
from kmast.data.normalization import content_hash


def number(row: dict[str, Any], key: str) -> Decimal:
    value = row.get(key)
    if value is None or value == "":
        raise ValueError("missing numeric source field")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite source field")
    return result


def parse_rest(
    body: dict[str, Any], request: MarketRequest, meta: Provenance
) -> tuple[Observation, ...]:
    if body.get("rt_cd") != "0":
        raise ValueError("unsuccessful source response")
    if (request.symbol, request.venue, request.tr_id) != (meta.symbol, meta.venue, meta.tr_id):
        raise ValueError("request/provenance mismatch")
    if meta.request_fingerprint != content_hash(request.model_dump(mode="json")):
        raise ValueError("cached request parameters do not match provenance")
    rows = (
        body.get("output2")
        if request.operation in {"daily", "index_daily", "minute_today", "minute_history"}
        else (body.get("output1") if request.operation == "quote" else body.get("output"))
    )
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("response schema mismatch")
    results = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid source row")
        common: dict[str, Any] = dict(
            symbol=meta.symbol,
            venue=meta.venue,
            session=meta.session,
            received_at=utc(meta.received_at),
            acquired_at=utc(meta.acquired_at),
            available_at=utc(meta.received_at),
            availability_method="OBSERVED_LIVE",
            availability_evidence="OBSERVED_COLLECTION_ONLY_NO_HISTORICAL_PIT_CLAIM",
            source_hash=meta.source_hash,
            parser_version=meta.parser_version,
            data_origin=meta.data_origin,
            price_basis=request.price_basis,
            timestamp_precision="RECEIPT_ONLY",
            exchange_date=meta.received_at.astimezone(KST).date(),
        )
        flags: list[str] = []
        if meta.session == "UNKNOWN":
            flags.append("SESSION_UNVERIFIED")
        if request.operation == "index_daily":
            day = datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date()
            if (
                request.start is None
                or request.end is None
                or not request.start <= day <= request.end
            ):
                raise ValueError("index response outside requested scope")
            common |= dict(
                kind="INDEX",
                exchange_date=day,
                timestamp_precision="DATE_ONLY",
                price=number(row, "bstp_nmix_prpr"),
                close=number(row, "bstp_nmix_prpr"),
                open=number(row, "bstp_nmix_oprc"),
                high=number(row, "bstp_nmix_hgpr"),
                low=number(row, "bstp_nmix_lwpr"),
                price_unit="INDEX_POINTS",
                volume_unit="UNVERIFIED",
                complete=day < meta.received_at.astimezone(KST).date(),
            )
            flags.append("INDEX_HISTORICAL_RELEASE_UNVERIFIED")
            key = day.isoformat()
        elif request.operation in {"daily", "minute_today", "minute_history"}:
            day = datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date()
            common["exchange_date"] = day
            if day > meta.received_at.astimezone(KST).date():
                raise ValueError("future bar date")
            daily = request.operation == "daily"
            if daily and (
                request.start is None
                or request.end is None
                or not request.start <= day <= request.end
            ):
                raise ValueError("response outside requested date scope")
            common |= dict(
                kind="DAILY" if daily else "MINUTE",
                open=number(row, "stck_oprc"),
                high=number(row, "stck_hgpr"),
                low=number(row, "stck_lwpr"),
                close=number(row, "stck_clpr" if daily else "stck_prpr"),
                volume=number(row, "acml_vol" if daily else "cntg_vol"),
            )
            if daily:
                if row.get("acml_tr_pbmn") not in (None, ""):
                    common["turnover"] = number(row, "acml_tr_pbmn")
                # A date is retained as a date: no invented exchange close/publication timestamp.
                common["timestamp_precision"] = "DATE_ONLY"
                common["complete"] = day < meta.received_at.astimezone(KST).date()
                if not common["complete"]:
                    flags.append("DAILY_FINALITY_UNVERIFIED")
                key = day.isoformat()
            else:
                local = datetime.strptime(
                    day.strftime("%Y%m%d") + row["stck_cntg_hour"], "%Y%m%d%H%M%S"
                ).replace(tzinfo=KST)
                # Timestamp label convention is not established by sample columns alone.
                # Conservative two-minute finality bound; locked until explicit interval evidence.
                common |= dict(
                    event_time=utc(local),
                    bar_start=utc(local),
                    bar_end=utc(local + timedelta(minutes=1)),
                    timestamp_precision="SECOND",
                    complete=False,
                )
                flags.append("BAR_INTERVAL_UNVERIFIED")
                if local + timedelta(minutes=2) > meta.received_at:
                    flags.append("INCOMPLETE_BAR")
                key = local.isoformat()
            if request.price_basis == "ADJUSTED":
                common["adjustment_asof"] = utc(meta.acquired_at)
                flags.append("ADJUSTMENT_HISTORY_UNVERIFIED")
        elif request.operation == "quote":
            flags.append("QUOTE_SOURCE_TIME_UNVERIFIED")
            common["exchange_date_basis"] = "RECEIPT_DATE_UNVERIFIED"
            common["source_time_of_day"] = row.get("aspr_acpt_hour")
            common |= dict(
                kind="QUOTE",
                bid=number(row, "bidp1"),
                ask=number(row, "askp1"),
                bid_size=number(row, "bidp_rsqn1"),
                ask_size=number(row, "askp_rsqn1"),
                complete=True,
            )
            key = meta.received_at.isoformat()
        elif request.operation == "index":
            flags.append("INDEX_SOURCE_TIME_UNVERIFIED")
            common["exchange_date_basis"] = "RECEIPT_DATE_UNVERIFIED"
            common |= dict(
                kind="INDEX",
                price=number(row, "bstp_nmix_prpr"),
                price_unit="INDEX_POINTS",
                volume_unit="UNVERIFIED",
                complete=True,
            )
            key = meta.received_at.isoformat()
        else:
            common |= dict(
                kind="TRADE",
                price=number(row, "stck_prpr"),
                volume=number(row, "acml_vol"),
                complete=True,
                volume_unit="UNVERIFIED",
            )
            flags.append("SNAPSHOT_NOT_TRADE_TICK")
            key = meta.received_at.isoformat()
        common["quality_flags"] = tuple(flags)
        common["record_id"] = observation_id(common["kind"], meta.symbol, meta.venue, key)
        results.append(Observation.model_validate(common))
    return tuple(sorted(results, key=lambda r: r.record_id))
