"""Freeze identity-only targets from DF008 rank; no KRX or price access."""

import json
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest


def main():
    previous = Path("artifacts/df008")
    targets = json.loads((previous / "document-targets.json").read_bytes())["originals"]
    evidence = json.loads((previous / "document-qualification.json").read_bytes())
    verified = {
        r["receipt"]
        for r in evidence
        if r["group"] == "originals"
        and all(
            r["states"][k] is True
            for k in ("DOCUMENT_VERIFIED", "CORPORATE_IDENTITY_VERIFIED", "EVENT_FAMILY_VERIFIED")
        )
    }
    assert len(verified) == 54
    chosen, corporations = [], set()
    for year in ("2022", "2023", "2024", "2025"):
        eligible = sorted(
            (r for r in targets if r["receipt"] in verified and r["receipt_date"].startswith(year)),
            key=lambda r: r["rank_sha256"],
        )
        count = 0
        for row in eligible:
            if row["corp_code"] in corporations:
                continue
            chosen.append(
                {
                    k: row[k]
                    for k in (
                        "receipt",
                        "corp_code",
                        "stock_code",
                        "receipt_date",
                        "source_market",
                        "rank_sha256",
                    )
                }
            )
            corporations.add(row["corp_code"])
            count += 1
            if count == 3:
                break
        assert count == 3
    assert len(chosen) == len(corporations) == 12
    identities = [{k: r[k] for k in ("receipt", "corp_code")} for r in chosen]
    protocol = dict(
        milestone="DF009",
        baseline_sha="304bd65da7b142e89c9c9bc74ee963c90625f7c1",
        baseline_tests=471,
        sampling=(
            "DF008 confirmed original cohort only. Three per year 2022/2023/2024/"
            "2025; ascending original frozen rank within year; skip any previousl"
            "y selected corporation across years. No price/PnL selection, no subs"
            "titutions after KRX results."
        ),
        targets=chosen,
        receipt_corporate_id_sha256=digest(canonical(identities)),
        DF008_target_sha256=digest((previous / "document-targets.json").read_bytes()),
        DF008_qualification_sha256=digest((previous / "document-qualification.json").read_bytes()),
        date_selection=(
            "Receipt date and previous Gregorian calendar date, at most two dates"
            " per event. A previous date may be a non-session: an empty response "
            "is missing evidence, never backfilled by a fabricated session or nea"
            "rby arbitrary snapshot. Exact date/market calls must be finalized an"
            "d approved after official API identity/access inspection."
        ),
        proposed_markets=["KOSPI", "KOSDAQ"],
        maximum_unique_requests=48,
        maximum_total_requests=96,
        maximum_attempts_per_request=2,
        authentication_authorized=False,
        service_paths=None,
        version=None,
        scope=(
            "Historical security basics only. Daily price API documentation can b"
            "e researched, but no price requests. No KIS or new DART authenticati"
            "on, key issuance, accounts, orders, cancels or LIVE."
        ),
        evidence_rules={
            "CORPORATE_IDENTITY_VERIFIED": (
                "Rehash original XML and explicit AREGCIK match to source corporation."
            ),
            "HISTORICAL_SECURITY_PRESENT": (
                "Actual successful dated KRX basic response with exact approved basDd"
                ", valid distinct standard and short codes, market and stock type. Cu"
                "rrent snapshots never prove historical existence."
            ),
            "CORP_STOCK_LINK_VERIFIED": (
                "Contemporaneous DART source six-digit code candidate plus matching h"
                "istorical KRX security, date, market, corporate issuer/name corrobor"
                "ation and listing chronology; corporate ID/name alone insufficient. "
                "Ambiguity, rename/merger/transfer/multiple-class conflict quarantine"
                "d unless independently resolved."
            ),
            "THEN_LISTED_STATUS_VERIFIED": (
                "Historical security evidence and LIST_DD<=event date, explicit match"
                "ing market. Does not imply session tradability."
            ),
            "DELISTING_AND_HALT_PENDING": "Separate dated halt/delisting evidence required.",
            "CORPORATE_ACTION_PENDING": "Separate dated action history required.",
            "PRICE_AND_SESSION_PENDING": "No new prices here; independent subsequent gate.",
        },
        decisions={
            "price_pilot": (
                "At least five verified historical mappings from three companies, the"
                "n-market evidence and safe relevant correction lineage. Propose at m"
                "ost three by frozen rank only. Never automatically authorize prices."
            ),
            "blocked": (
                "Separate unavailable API/key/service, historical date not supplied, "
                "issuer/security conflict, security-change-history missing, halt/acti"
                "on/session missing. No failure is NO_ALPHA."
            ),
            "nulls": (
                "Unobserved fields, publication timestamps and costs per verified eve"
                "nt remain NULL; hypothetical fixtures never count as market evidence"
                "."
            ),
        },
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(Path("artifacts/df009/DF009_PROTOCOL.json"), protocol)
    print(
        json.dumps(
            dict(
                selected=12,
                distinct_corporations=12,
                identity_sha256=protocol["receipt_corporate_id_sha256"],
            )
        )
    )


if __name__ == "__main__":
    main()
