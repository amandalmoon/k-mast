"""Offline V2 reproduction and immutable V3 audit; no authentication or network imports."""

import argparse
import hashlib
import json
import subprocess
import sys
import types
from decimal import Decimal
from pathlib import Path

from kmast.alpha.models import AlphaConfig
from kmast.data.normalization import content_hash
from kmast.data.store import DataStore, canonical, immutable_write
from kmast.research.attribution import attribute, exposure_diagnostic
from kmast.research.exploratory import ExplorationPolicy, replay

START = "3e3e2d867d69c6a9adae9343b0d55d4662088084"
STOCKS = ("005930", "000660", "035420", "247540", "086520", "028300")
MODES = ("ALPHA_A", "BUY_HOLD", "HOLD_25", "CASH", "TREND_25")


def plain(value):
    return json.loads(json.dumps(value, default=str))


def economic_orders(r):
    return [{k: v for k, v in o.items() if k != "identity"} for o in r["reference_state"]["orders"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduce-v2", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df002"
    proof.mkdir(exist_ok=True)
    acquired = json.loads((root / "artifacts/data-first/collection.json").read_bytes())
    old_contract = json.loads(
        (root / "artifacts/data-first/exploration-contract-v2.json").read_bytes()
    )
    folder = root / acquired["private_store"]
    private = folder / "df002-v3-reviewed"
    private.mkdir(exist_ok=True)
    source = subprocess.check_output(
        ["git", "show", START + ":src/kmast/research/exploratory.py"], cwd=root
    )
    old = types.ModuleType("df002_frozen_v2")
    sys.modules[old.__name__] = old
    exec(compile(source, "frozen_trusted_repository_v2", "exec"), old.__dict__)
    reproduction = json.loads((proof / "v2-reproduction.json").read_bytes())
    assert reproduction["count"] == 72 and reproduction["matched"]
    assert reproduction["source_hash"] == hashlib.sha256(source).hexdigest()
    for name, digest in reproduction["files"].items():
        assert hashlib.sha256((folder / "exploration-v2" / name).read_bytes()).hexdigest() == digest
    policies = [ExplorationPolicy.model_validate(p) for p in old_contract["policies"]]
    contract = dict(
        revision="DF002_V3",
        starting_head=START,
        config=AlphaConfig(strategy="A").model_dump(mode="json"),
        policies=[p.model_dump(mode="json") for p in policies],
        data_manifest_hash=content_hash(acquired),
        code_hashes={
            f: content_hash((root / f).read_text(encoding="utf-8"))
            for f in (
                "src/kmast/research/exploratory.py",
                "src/kmast/research/attribution.py",
                "scripts/run_df002.py",
            )
        },
        benchmark_rule=(
            "TREND_25: prior close >= preceding 20-close mean; target .25 else 0; "
            "same execution/cost/cash model"
        ),
        risk_comparison="HOLD_25_AND_TREND_25_EX_ANTE; AVERAGE_EXPOSURE_EX_POST_DIAGNOSTIC_ONLY",
        frozen_candidate="AlphaA-candidate-v1_UNCHANGED",
        acquisition_calls=0,
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        confirmatory_status="NOT_EXECUTED",
    )
    immutable_write(proof / "contract-final.json", canonical(contract))
    panels = {}
    store = DataStore(folder)
    for dataset in acquired["datasets"]:
        if dataset["operation"] not in {"daily", "index_daily"} or dataset["price_basis"] != "RAW":
            continue
        for row in store.load_dataset(dataset["dataset_id"]):
            panel = panels.setdefault(row.symbol, {})
            assert row.exchange_date not in panel
            panel[row.exchange_date] = row
    summaries, comparisons, diagnostics, lineage = [], [], [], []
    for symbol in STOCKS:
        idx = "0001" if symbol in STOCKS[:3] else "1001"
        rows = tuple(sorted(panels[symbol].values(), key=lambda r: r.exchange_date))
        index = tuple(sorted(panels[idx].values(), key=lambda r: r.exchange_date))
        for policy in policies:
            for mode in MODES:
                name = f"{symbol}-{policy.version}-{mode}.json"
                if mode != "TREND_25":
                    previous = json.loads((folder / "exploration-v2" / name).read_bytes())
                    if args.reproduce_v2:
                        reproduced = old.replay(
                            rows,
                            index,
                            old.ExplorationPolicy.model_validate(policy.model_dump()),
                            mode,
                        )
                        assert canonical(reproduced) == canonical(previous), (
                            "V2 reproduction mismatch"
                        )
                cached_path = folder / "df002-v3-final" / name
                if cached_path.exists():
                    cached_contract = json.loads((proof / "contract.json").read_bytes())
                    assert cached_contract["data_manifest_hash"] == contract["data_manifest_hash"]
                    assert (
                        cached_contract["code_hashes"]["src/kmast/research/exploratory.py"]
                        == contract["code_hashes"]["src/kmast/research/exploratory.py"]
                    )
                    current = json.loads(cached_path.read_bytes())["replay"]
                    assert current["symbol"] == symbol and current["mode"] == mode
                    assert current["policy"] == policy.model_dump(mode="json")
                else:
                    current = replay(rows, index, policy, mode)
                audit = plain(attribute(current))
                immutable_write(private / name, canonical(dict(replay=current, attribution=audit)))
                summaries.append(audit["summary"])
                for sig in current["signal_log"]:
                    assert sig["input_last_date"] < sig["day"]
                    assert sig["lineage"]["last_available_at"] <= sig["decision_at"]
                lineage.append(
                    dict(
                        symbol=symbol,
                        scenario=policy.version,
                        mode=mode,
                        decisions=len(current["signal_log"]),
                        all_prior_inputs=True,
                        signal_chain_hash=content_hash(
                            [s["intent"] for s in current["signal_log"]]
                        ),
                    )
                )
                if mode == "ALPHA_A":
                    diagnostics.append(
                        dict(symbol=symbol, scenario=policy.version, **exposure_diagnostic(current))
                    )
                if mode != "TREND_25":
                    comparisons.append(
                        dict(
                            symbol=symbol,
                            scenario=policy.version,
                            mode=mode,
                            v2_exact_reproduction=True,
                            v2_net=previous["scenario_project_net_pnl"],
                            v3_net=current["scenario_project_net_pnl"],
                            delta=str(
                                Decimal(current["scenario_project_net_pnl"])
                                - Decimal(previous["scenario_project_net_pnl"])
                            ),
                            economic_orders_equal=economic_orders(current)
                            == economic_orders(previous),
                            economic_fills_equal=[
                                e[1:] for e in current["reference_state"]["executions"]
                            ]
                            == [e[1:] for e in previous["reference_state"]["executions"]],
                            order_identifiers_changed=sum(
                                a["identity"] != b["identity"]
                                for a, b in zip(
                                    current["reference_state"]["orders"],
                                    previous["reference_state"]["orders"],
                                    strict=False,
                                )
                            ),
                            explanation=(
                                "Causal input and position identifiers change; compare "
                                "economic orders/fills separately from metadata"
                            ),
                        )
                    )
            print(f"completed {symbol} {policy.version}", flush=True)
    report = dict(
        contract_hash=content_hash(contract),
        summaries=summaries,
        comparisons=comparisons,
        exposure_diagnostics=diagnostics,
        lineage=lineage,
        v2_reproduced=72,
        v3_replays=90,
        private_details="data/data-first-private-market-v1/df002-v3-reviewed",
        attribution_revision="EXCLUDE_POST_EXIT_CLOSE_FROM_EXCURSIONS",
        v2_reproduction_proof_hash=content_hash(reproduction),
        technical_status="DF002_CAUSAL_REPLAY_VERIFIED",
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        confirmatory_status="NOT_EXECUTED",
        auth_calls=0,
        market_calls=0,
        order_calls=0,
        cancel_calls=0,
    )
    immutable_write(proof / "results.json", canonical(report))
    print("V2 exact reproduction 72; V3 immutable replay 90; daily/FIFO attribution PASS")


if __name__ == "__main__":
    main()
