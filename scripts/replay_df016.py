"""Independent synthetic timing trace, never real market or economic evidence."""

import json
from datetime import timedelta
from pathlib import Path

from kmast.data.bar_orb import breakout, later_snapshot, opening_range, parse_bars, parse_quote
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import digest
from tests.test_df016 import SESSION, payload, receipt, row


def main():
    root = Path("data/data-first-private-df016-synthetic")
    rec = receipt()
    opening_raw = payload([row(i) for i in range(15)])
    immutable_write(root / "opening-range.bin", opening_raw)
    rows = parse_bars(opening_raw, rec, SESSION)
    ranges = [opening_range(rows, n, SESSION, rec.validated_at) for n in (5, 15)]
    raw = payload([row(15, stck_prpr="110", stck_hgpr="112")])
    immutable_write(root / "breakout.bin", raw)
    post = parse_bars(raw, rec, SESSION)[0]
    signals = [breakout(w, post, rec.validated_at) for w in ranges]
    qr = receipt(17, "FHKST01010200")
    quote_raw = json.dumps(
        dict(
            rt_cd="0",
            output1=dict(bidp1="111", askp1="112", aspr_acpt_hour=qr.request_at.strftime("%H%M%S")),
        )
    ).encode()
    immutable_write(root / "quote.bin", quote_raw)
    quote = parse_quote(quote_raw, qr, SESSION)
    report = dict(
        origin="SYNTHETIC",
        oracle="Explicit START label/clock/market/correction/volume/price "
        "assumptions for software tests only; not KIS service confirmation",
        request_at=rec.request_at.isoformat(),
        response_complete_at=rec.response_at.isoformat(),
        validation_complete_at=rec.validated_at.isoformat(),
        quote_request_at=qr.request_at.isoformat(),
        quote_response_at=qr.response_at.isoformat(),
        cases=[
            dict(
                minutes=w.minutes,
                range_end=w.end.isoformat(),
                high=str(w.high),
                low=str(w.low),
                signal_available_at=s.available_at.isoformat(),
                signal_blocked_before_validation=breakout(
                    w, post, rec.validated_at - timedelta(microseconds=1)
                )
                is None,
                later_snapshot=later_snapshot(s, quote),
                fill=quote.is_fill,
                price_source_sha256=digest(raw),
                range_source_sha256=digest(opening_raw),
                quote_source_sha256=digest(quote_raw),
            )
            for w, s in zip(ranges, signals, strict=True)
        ],
        actual_market_evidence=False,
        actual_profit=None,
    )
    atomic_json(Path("artifacts/df016/synthetic-trace.json"), report)
    print("DF016 synthetic ORB5/15 availability/later-snapshot trace PASS; fills/profit unverified")


if __name__ == "__main__":
    main()
