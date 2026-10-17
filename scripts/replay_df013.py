"""Explicit synthetic opening stream; no real prices, sockets, credentials or PnL."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from kmast.data.models import KST
from kmast.data.orb_observation import (
    COLUMNS,
    Context,
    FrameArchive,
    OpeningResearch,
    Receipt,
    parse,
)
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest


def main():
    private = Path("data/data-first-private-df013-synthetic")
    opening = datetime(2026, 10, 19, 9, tzinfo=KST)
    context = Context(opening.date(), "KOSPI", opening, True, True, True, "SYNTHETIC_ONLY")
    engine = OpeningResearch(context, "000000")
    archive = FrameArchive(private / "sample-archive-utc-v2")
    for channel in COLUMNS:
        engine.acknowledge(channel, opening - timedelta(seconds=1))
    frame_hashes, quantity, turnover = [], 0, 0
    for second in range(901):
        price = 100 if second < 300 else (200 if second < 900 else 1000)
        quantity += 1
        turnover += price
        for index, channel in enumerate(COLUMNS):
            row = dict.fromkeys(COLUMNS[channel], "0")
            row.update(MKSC_SHRN_ISCD="000000", MARKET_CLS_CODE="2", HOUR_CLS_CODE="0")
            stamp = opening + timedelta(seconds=second)
            if channel == "H0STCNT0":
                row.update(
                    BSOP_DATE=stamp.strftime("%Y%m%d"),
                    STCK_CNTG_HOUR=stamp.strftime("%H%M%S"),
                    STCK_PRPR=str(price),
                    CNTG_VOL="1",
                    ACML_VOL=str(quantity),
                    ACML_TR_PBMN=str(turnover),
                    TRHT_YN="N",
                )
            else:
                row.update(BSOP_HOUR=stamp.strftime("%H%M%S"))
                for level in range(1, 11):
                    row.update(
                        {
                            f"ASKP{level}": str(price + level),
                            f"BIDP{level}": str(price - level),
                            f"ASKP_RSQN{level}": "100",
                            f"BIDP_RSQN{level}": "100",
                        }
                    )
            raw = ("0|" + channel + "|001|" + "^".join(row[c] for c in COLUMNS[channel])).encode()
            receipt = Receipt(
                stamp + timedelta(milliseconds=100 + index * 100),
                second * 10**9 + (index + 1) * 100000000,
                "SYNTHETIC-ONLY",
                second * 2 + index + 1,
            )
            # Every raw message is immutable; a small separate archive tests restart journal.
            immutable_write(private / "frames" / (digest(raw) + ".bin"), raw)
            ticks = parse(raw, receipt, context)
            if second == 0:
                if len(archive.records) < 2:
                    archive.append(raw, receipt, context)
            engine.ingest(ticks[0])
            frame_hashes.append(digest(raw))
    archive.verify()
    payload = canonical(frame_hashes)
    immutable_write(private / "frame-hashes.json", payload)
    asof = opening + timedelta(minutes=15, seconds=2)
    assert engine.range_high(5, opening + timedelta(minutes=5) - timedelta(microseconds=1)) is None
    assert engine.range_high(5, asof) == Decimal(100)
    assert engine.range_high(15, asof) == Decimal(200)
    assert not engine.defects
    atomic_json(
        Path("artifacts/df013/synthetic-observation.json"),
        dict(
            origin="SYNTHETIC",
            empirical_market_evidence=False,
            modeled_profit=None,
            messages=len(frame_hashes),
            raw_hash_manifest_sha256=digest(payload),
            opening5_high="100",
            opening15_high="200",
            vwap=str(engine.vwap(asof)),
            rvol=engine.rvol_status(),
            observed_defects=[],
            actual_network_calls=0,
            quality_scope=(
                "Test-only verified context; provider sequence and real "
                "VI/correction coverage remain unavailable"
            ),
        ),
    )
    print(json.dumps(dict(origin="SYNTHETIC", messages=len(frame_hashes), network_calls=0)))


if __name__ == "__main__":
    main()
