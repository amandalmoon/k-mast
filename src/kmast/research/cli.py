"""No-network qualification command. Absent private data is HOLD, never synthetic profit."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kmast.alpha.models import AlphaConfig
from kmast.alpha.readiness import observation_bar
from kmast.core.study import StudyContract
from kmast.data.models import Observation
from kmast.data.normalization import content_hash
from kmast.data.store import DataStore, canonical, immutable_write
from kmast.portfolio.data_gate import ResearchDataGate
from kmast.research.economics import economic_acceptance
from kmast.research.qualification import LicenseScope, g1, quality_summary
from kmast.research.validation import CandidateFreeze

METRICS = (
    "gross_market_pnl_krw",
    "fees_and_taxes_krw",
    "execution_cost_krw",
    "recurring_account_opex_krw",
    "recurring_external_opex_krw",
    "NET_OPERATING_PNL_KRW",
    "nav",
    "twr",
    "excess_over_cash_krw",
    "expectancy_per_trade",
    "win_rate",
    "average_trade_pnl",
    "max_drawdown",
    "sharpe",
    "sortino",
    "turnover",
    "average_holding_seconds",
    "unfilled_fraction",
    "capital_occupancy",
    "capacity_krw",
    "symbol_exposure",
    "sector_exposure",
    "market_exposure",
)


def run(
    output: Path, private_store: Path | None = None, manifest: Path | None = None
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    config = AlphaConfig(strategy="A")
    license_scope = LicenseScope(
        provider="KIS",
        document_title="OPEN_API_CUSTOMER_TERMS_ARTICLE_5_3",
        document_version="PUBLIC_API_VERSION_28_MODIFIED_2024-04-11",
        official_url="https://apiportal.koreainvestment.com/api/terms/public?termsType=MARKET",
        checked_at=datetime.now(UTC),
        personal_program_use="CONFIRMED",
        strategy_development="CONFIRMED",
        raw_publication="PROHIBITED",
        third_party_data="PROHIBITED",
    )
    rows: tuple[Observation, ...] = ()
    dataset_metadata = []
    manifest_hash = content_hash("DATA_NOT_ACCESSIBLE")
    if private_store is not None and manifest is not None:
        contents = manifest.read_bytes()
        manifest_hash = hashlib.sha256(contents).hexdigest()
        collection = json.loads(contents)
        store = DataStore(private_store)
        all_rows: list[Observation] = []
        for item in collection["datasets"]:
            loaded = store.load_dataset(item["dataset_id"])
            all_rows.extend(loaded)
            dataset_metadata.append(
                dict(
                    dataset_id=item["dataset_id"],
                    rows=len(loaded),
                    source_hashes=sorted({r.source_hash for r in loaded}),
                    acquired_at=sorted({r.acquired_at.isoformat() for r in loaded}),
                    received_at=sorted({r.received_at.isoformat() for r in loaded}),
                    parser_versions=sorted({r.parser_version for r in loaded}),
                    availability_methods=sorted({r.availability_method.value for r in loaded}),
                    timestamp_precisions=sorted({r.timestamp_precision for r in loaded}),
                    sessions=sorted({r.session for r in loaded}),
                    price_basis=item["price_basis"],
                    start=item["start"],
                    end=item["end"],
                    symbol=item["symbol"],
                    source_environment="PAPER_REPORTED_KM004_NOT_ENCODED_IN_ROW",
                )
            )
        rows = tuple(all_rows)
    quality = quality_summary(rows)
    gate = ResearchDataGate(
        strategy="A",
        real_rows=quality.real_rows,
        synthetic_rows=quality.synthetic_rows,
        symbols=tuple(sorted({r.symbol for r in rows})),
        start=min((r.exchange_date for r in rows), default=None),
        end=max((r.exchange_date for r in rows), default=None),
        hashes_verified=bool(rows),
        origin_verified=bool(rows),
        source_verified=bool(rows),
    )
    config_hash = content_hash(config.model_dump(mode="json"))
    source_root = Path(__file__).resolve().parents[1]
    source_hash = content_hash(
        {
            name: hashlib.sha256((source_root / "alpha" / name).read_bytes()).hexdigest()
            for name in ("rules.py", "models.py")
        }
    )
    freeze = CandidateFreeze(
        config_hash=config_hash,
        source_hash=source_hash,
        data_manifest_hash=manifest_hash,
        frozen_at=datetime.now(UTC),
        study=StudyContract(),
        candidate_search_count=1,
        lineage=("KM003:AlphaA-candidate-v1:UNCHANGED",),
    )
    freeze_path = output / "candidate-freeze.json"
    if freeze_path.exists():
        prior = CandidateFreeze.model_validate_json(freeze_path.read_bytes())
        if (prior.config_hash, prior.source_hash, prior.data_manifest_hash) != (
            config_hash,
            source_hash,
            manifest_hash,
        ):
            raise PermissionError("changed candidate/data requires new study output and lineage")
        freeze = prior
    immutable_write(freeze_path, canonical(freeze.model_dump(mode="json")))
    adapter_rejections = 0
    for row in rows:
        if row.kind == "DAILY" and row.price_basis == "RAW":
            try:
                observation_bar(row, row.record_id)
            except ValueError:
                adapter_rejections += 1
    status = g1(gate, license_scope, quality)
    result = dict(
        status="KM005_DATA_HOLD",
        data_access="LOCAL_VERIFIED" if rows else "DATA_NOT_ACCESSIBLE",
        license_status="LICENSE_UNVERIFIED",
        license_scope=license_scope.model_dump(mode="json"),
        g1=status,
        blockers=gate.blockers(),
        quality=quality.model_dump(mode="json"),
        datasets=dataset_metadata,
        candidate_config=config.model_dump(mode="json"),
        candidate_freeze=freeze.model_dump(mode="json"),
        candidate_freeze_id=freeze.identity,
        g0="HOLD_NOT_FROZEN_ECONOMIC_CONTRACT",
        missing_g0_fields=freeze.study.missing_economic_fields(),
        gates=economic_acceptance(False, False, False, False),
        raw_alpha_adapter_rejections=adapter_rejections,
        actual_signal_execution="NOT_EXECUTED_G1_HOLD",
        calculation_mode="NOT_EXECUTED",
        metric_provenance=tuple(d["dataset_id"] for d in dataset_metadata),
        metrics={name: None for name in METRICS},
        metric_status="INSUFFICIENT_EVIDENCE",
        baseline_comparisons={
            name: "NOT_EXECUTED_G1_HOLD"
            for name in (
                "CASH",
                "SIMPLE_HOLD",
                "SIMPLE_TREND",
                "AlphaA-candidate-v1",
                "PBASE_FIXED",
                "PBASE_RISK",
            )
        },
        kis_auth_calls=0,
        market_calls=0,
        account_calls=0,
        actual_orders=0,
        actual_cancels=0,
    )
    (output / "qualification.json").write_bytes(canonical(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/km005/offline"))
    parser.add_argument("--private-store", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if (args.private_store is None) != (args.manifest is None):
        parser.error("private store and manifest must be provided together")
    result = run(args.output, args.private_store, args.manifest)
    print(json.dumps({k: result[k] for k in ("status", "data_access", "g1", "gates")}, indent=2))


if __name__ == "__main__":
    main()
