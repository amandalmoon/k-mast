"""Metadata-only stratified document pilot selection; never opens new documents/prices."""

import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest


def rank(receipt, kind):
    return digest(("DF008_DOCUMENT_PILOT_V1:" + kind + ":" + receipt).encode())


def main():
    path = Path("data/data-first-private-df007-census-v2/candidate-register.json")
    candidates = json.loads(path.read_bytes())
    originals = [c for c in candidates if c["family"] == "D1"]
    assert len(originals) == 620
    groups = defaultdict(list)
    for c in originals:
        market = c["source_market"] if c["source_market"] in {"Y", "K"} else "UNKNOWN"
        groups[(c["receipt_date"][:4], market, c["regime"] == "BEAR")].append(c)
    chosen, strata = [], []
    for year in ("2022", "2023", "2024", "2025"):
        quotas = {
            "Y": 6 if int(year) % 2 == 0 else 7,
            "K": 7 if int(year) % 2 == 0 else 6,
            "UNKNOWN": 2,
        }
        for market, total in quotas.items():
            bears = groups[(year, market, True)]
            others = groups[(year, market, False)]
            bear_quota = min(1, len(bears)) if market != "UNKNOWN" else 0
            non_quota = min(total - bear_quota, len(others))
            bear_quota = min(len(bears), total - non_quota)
            assert bear_quota + non_quota == total
            for is_bear, pool, quota in ((True, bears, bear_quota), (False, others, non_quota)):
                if not pool:
                    continue
                probability = Fraction(quota, len(pool))
                strata.append(
                    dict(
                        year=year,
                        source_market=market,
                        bear=is_bear,
                        population=len(pool),
                        selected=quota,
                        inclusion_probability=str(probability),
                    )
                )
                for c in sorted(pool, key=lambda c: rank(c["receipt"], "ORIGINAL"))[:quota]:
                    chosen.append(
                        {
                            k: c[k]
                            for k in (
                                "receipt",
                                "corp_code",
                                "stock_code",
                                "source_market",
                                "receipt_date",
                                "regime",
                                "old_consumed_event",
                            )
                        }
                        | dict(
                            rank_sha256=rank(c["receipt"], "ORIGINAL"),
                            stratum=dict(year=year, source_market=market, bear=is_bear),
                            inclusion_probability=str(probability),
                        )
                    )
    assert len(chosen) == 60 and Counter(c["receipt_date"][:4] for c in chosen) == {
        str(y): 15 for y in range(2022, 2026)
    }
    raw = json.loads(
        Path("data/data-first-private-df007-census-v2/all-normalized-disclosures.json").read_bytes()
    )["records"]
    corps = {c["corp_code"] for c in chosen}
    correction_pool = [
        r
        for r in raw
        if r["family"] == "D1" and r["revision"] != "ORIGINAL" and r["row"]["corp_code"] in corps
    ]
    revisions = []
    for item in sorted(correction_pool, key=lambda r: rank(r["row"]["rcept_no"], "REVISION"))[:40]:
        r = item["row"]
        revisions.append(
            dict(
                receipt=r["rcept_no"],
                corp_code=r["corp_code"],
                receipt_date=r["rcept_dt"],
                revision=item["revision"],
                potential_relation_only=True,
                rank_sha256=rank(r["rcept_no"], "REVISION"),
            )
        )
    cache = json.loads(Path("data/data-first-private-df006-events/manifest.json").read_bytes())[
        "documents"
    ]
    targets = [
        dict(receipt=c["receipt"], kind="ORIGINAL", cached=c["receipt"] in cache) for c in chosen
    ] + [
        dict(receipt=c["receipt"], kind="REVISION", cached=c["receipt"] in cache) for c in revisions
    ]
    selection = dict(
        version="DF008_METADATA_STRATIFIED_V1",
        population=620,
        source_candidate_register_sha256=digest(path.read_bytes()),
        strata=strata,
        originals=chosen,
        revisions=revisions,
        potential_revision_pool=len(correction_pool),
        revision_overflow=max(0, len(correction_pool) - 40),
        targets=targets,
        target_count=len(targets),
        cached_targets=sum(t["cached"] for t in targets),
        maximum_requests=200,
        network_approved=False,
    )
    atomic_json(Path("artifacts/df008/document-targets.json"), selection)
    print(
        json.dumps(
            dict(
                originals=len(chosen),
                bear_originals=sum(c["regime"] == "BEAR" for c in chosen),
                unknown_market_originals=sum(c["source_market"] not in {"Y", "K"} for c in chosen),
                revisions=len(revisions),
                revision_pool=len(correction_pool),
                cached_targets=selection["cached_targets"],
                target_count=len(targets),
            )
        )
    )


if __name__ == "__main__":
    main()
