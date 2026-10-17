"""Execute sealed DF003 protocol using only saved KIS observations; immutable new store."""

import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import DataStore, canonical, immutable_write
from kmast.research.exploratory import ExplorationPolicy
from kmast.research.holding_analysis import analyze_holding, classify, exposure_pair
from kmast.research.hypotheses import hypothesis_replay, reduction_status


def plain(value):
    return json.loads(json.dumps(value, default=str))


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df003"
    protocol_bytes = (proof / "DF003_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    seal = json.loads((proof / "protocol-seal.json").read_bytes())
    assert hashlib.sha256(protocol_bytes).hexdigest() == seal["protocol_sha256"]
    assert protocol["trials"]["total_references"] == 216
    acquired = json.loads((root / "artifacts/data-first/collection.json").read_bytes())
    old_contract = json.loads(
        (root / "artifacts/data-first/exploration-contract-v2.json").read_bytes()
    )
    policies = [ExplorationPolicy.model_validate(p) for p in old_contract["policies"]]
    folder = root / acquired["private_store"]
    target = folder / "df003-hypotheses-v1"
    target.mkdir(exist_ok=True)
    code_paths = [
        "src/kmast/research/exploratory.py",
        "src/kmast/research/attribution.py",
        "src/kmast/research/hypotheses.py",
        "src/kmast/research/holding_analysis.py",
        "scripts/run_df003.py",
    ]
    contract = dict(
        protocol_sha256=seal["protocol_sha256"],
        source_hashes={
            p: hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in code_paths
        },
        collection_manifest_sha256=hashlib.sha256(
            (root / "artifacts/data-first/collection.json").read_bytes()
        ).hexdigest(),
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    immutable_write(proof / "implementation-contract.json", canonical(contract))
    panels = {}
    store = DataStore(folder)
    for dataset in acquired["datasets"]:
        if dataset["operation"] not in {"daily", "index_daily"} or dataset["price_basis"] != "RAW":
            continue
        for row in store.load_dataset(dataset["dataset_id"]):
            panel = panels.setdefault(row.symbol, {})
            assert row.exchange_date not in panel
            panel[row.exchange_date] = row
    summaries = []
    hashes = {}
    a0_matches = []
    safety_details = []
    for symbol in protocol["symbols"]:
        idx = "0001" if symbol in protocol["symbols"][:3] else "1001"
        rows = tuple(sorted(panels[symbol].values(), key=lambda r: r.exchange_date))
        index = tuple(sorted(panels[idx].values(), key=lambda r: r.exchange_date))
        for policy in policies:
            for name in ("A0", "A1", "A2", "A3", "T0", "T1", "T2", "T3", *protocol["baselines"]):
                if name in protocol["baselines"]:
                    old_path = (
                        folder / "df002-v3-reviewed" / f"{symbol}-{policy.version}-{name}.json"
                    )
                    result = json.loads(old_path.read_bytes())["replay"]
                else:
                    result = hypothesis_replay(rows, index, policy, name)
                if name == "A0":
                    previous = json.loads(
                        (
                            folder / "df002-v3-reviewed" / f"{symbol}-{policy.version}-ALPHA_A.json"
                        ).read_bytes()
                    )["replay"]
                    assert canonical(result) == canonical(previous), "A0 diverged from frozen V3"
                    a0_matches.append(dict(symbol=symbol, scenario=policy.version, exact=True))
                analysis = plain(analyze_holding(result, name))
                path = target / f"{symbol}-{policy.version}-{name}.json"
                body = canonical(dict(candidate=name, replay=result, attribution=analysis))
                immutable_write(path, body)
                hashes[path.name] = hashlib.sha256(body).hexdigest()
                s = analysis["summary"]
                assert s["days"] == 223 and D(s["capital"]) == D(10000000)
                summaries.append(s)
                if name == "A0" and policy.fill_fraction == D(".5"):
                    safety_details.append(dict(symbol=symbol, **s["execution_safety"]))
            print(f"completed {symbol} {policy.version}: 12 references", flush=True)
    pairs = []

    def lookup(symbol, scenario, name):
        return next(
            s
            for s in summaries
            if (s["symbol"], s["scenario"], s["candidate"]) == (symbol, scenario, name)
        )

    for symbol in protocol["symbols"]:
        for policy in policies:
            scenario = policy.version
            for i in range(4):
                a, t = (
                    lookup(symbol, scenario, "A" + str(i)),
                    lookup(symbol, scenario, "T" + str(i)),
                )
                pairs.append(
                    dict(
                        symbol=symbol,
                        scenario=scenario,
                        type="ENTRY_ONLY_MODEL_CONTROL",
                        a=a["candidate"],
                        b=t["candidate"],
                        net_delta=str(D(a["project_net"]) - D(t["project_net"])),
                        exposure_control=exposure_pair(a, t),
                    )
                )
            for name, other in (("A1", "A0"), ("A2", "A0"), ("A3", "A0"), ("A3", "A2")):
                a, b = lookup(symbol, scenario, name), lookup(symbol, scenario, other)
                pairs.append(
                    dict(
                        symbol=symbol,
                        scenario=scenario,
                        type="HOLDING_EXIT_MODEL_CONTROL",
                        a=name,
                        b=other,
                        net_delta=str(D(a["project_net"]) - D(b["project_net"])),
                        mean_exposure_delta=str(
                            D(a["average_close_exposure"]) - D(b["average_close_exposure"])
                        ),
                        mdd_delta=str(D(a["mdd"]) - D(b["mdd"])),
                        exposure_control=exposure_pair(a, b),
                    )
                )
    findings = classify(summaries)
    forced_probes = [
        reduction_status(True, 1, pending, state, forced=True)
        for state in ("UNKNOWN", "HALTED", "MODEL_ONLY")
        for pending in (0, 1)
    ]
    report = dict(
        protocol_sha256=seal["protocol_sha256"],
        technical_status="DF003_HYPOTHESIS_AUDIT_VERIFIED",
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        confirmatory_status="NOT_EXECUTED",
        independent_references=216,
        summaries=summaries,
        comparisons=pairs,
        candidate_findings=findings,
        a0_exact_v3_matches=a0_matches,
        partial_original_safety=safety_details,
        forced_reduction_probes=forced_probes,
        private_details=target.relative_to(root).as_posix(),
        private_hashes=hashes,
        authentication_calls=0,
        market_calls=0,
        account_calls=0,
        order_calls=0,
        cancel_calls=0,
        ewy_performance=None,
        df004_started=False,
    )
    immutable_write(proof / "results.json", canonical(report))
    print("DF003: 216 independent references; original A0 exact matches 18; no new API calls")


if __name__ == "__main__":
    main()
