"""Stream completed, immutable symbol histories into bounded offline worker processes."""

import argparse
import ast
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from kmast.data.models import Observation
from kmast.data.panel_acquisition import process_lock
from kmast.data.store import DataStore, canonical, digest, immutable_write
from kmast.research.domestic_panel import (
    MODELS,
    SCENARIOS,
    WINDOWS,
    economic_fields,
    study_reference,
    window_inputs,
)

SOURCE = Path("data/data-first-private-df005-panel")
TARGET = Path("data/data-first-private-df005-replays-v3")


def plain(value):
    return json.loads(json.dumps(value, default=str))


def worker(input_file):
    payload = json.loads(Path(input_file).read_bytes())
    stock = tuple(Observation.model_validate(r) for r in payload["stock"])
    index = tuple(Observation.model_validate(r) for r in payload["index"])
    exclusions = frozenset(date.fromisoformat(d) for d in payload["exclusions"])
    summaries = []
    for scenario in SCENARIOS:
        for model in MODELS:
            name = f"{payload['symbol']}-W{payload['window']}-{scenario}-{model}.json"
            path = TARGET / "references" / name
            prior = Path("data/data-first-private-df005-replays-v2/references") / name
            if not path.exists() and prior.exists():
                previous = json.loads(prior.read_bytes())
                assert previous["input_sha256"] == digest(Path(input_file).read_bytes())
                immutable_write(path, prior.read_bytes())
            if path.exists():
                result = json.loads(path.read_bytes())
            else:
                result = plain(study_reference(stock, index, model, scenario, exclusions))
                result.update(
                    input_sha256=digest(Path(input_file).read_bytes()),
                    window=payload["window"],
                    eligibility=payload["eligibility"],
                )
                immutable_write(path, canonical(result))
            assert result["input_sha256"] == digest(Path(input_file).read_bytes())
            summary = result["analysis"]["summary"]
            summary.update(
                window=payload["window"],
                private_file=name,
                private_sha256=digest(path.read_bytes()),
            )
            summaries.append(summary)
    return summaries


def load_histories(manifest, symbol, basis):
    store = DataStore(SOURCE)
    selected = {}
    for page in manifest["pages"].values():
        request = page["request"]
        if request["symbol"] != symbol or request["price_basis"] != basis:
            continue
        rows = store.load_dataset(page["dataset_id"])
        assert (
            digest(canonical([r.model_dump(mode="json") for r in rows])) == page["normalized_hash"]
        )
        for row in rows:
            old = selected.get(row.exchange_date)
            if old is not None and economic_fields(old) != economic_fields(row):
                raise ValueError("CONFLICTING_ECONOMIC_REVISION_REQUIRES_LINEAGE")
            selected.setdefault(row.exchange_date, row)
    return tuple(selected[d] for d in sorted(selected))


def active_collection():
    try:
        with process_lock(SOURCE / "process.lock"):
            return False
    except PermissionError:
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-collection", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=4)
    args = parser.parse_args()
    protocol_file = Path("artifacts/df005/DF005_PROTOCOL.json")
    protocol = json.loads(protocol_file.read_bytes())
    calendar_file = Path("artifacts/df005/session-eligibility-v1.json")
    calendar = json.loads(calendar_file.read_bytes())
    symbols = protocol["kospi"] + protocol["kosdaq"]
    TARGET.mkdir(parents=True, exist_ok=True)
    code = [
        "scripts/run_df005.py",
        "src/kmast/research/domestic_panel.py",
        "src/kmast/research/exploratory.py",
        "src/kmast/research/hypotheses.py",
        "src/kmast/alpha/reference.py",
        "src/kmast/research/attribution.py",
        "src/kmast/research/holding_analysis.py",
        "src/kmast/research/panel_attribution.py",
    ]
    contract = dict(
        protocol_sha256=digest(protocol_file.read_bytes()),
        session_eligibility_sha256=digest(calendar_file.read_bytes()),
        code_hashes={p: digest(Path(p).read_bytes()) for p in code},
        workers=args.workers,
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    previous_root = Path("data/data-first-private-df005-replays-v2")
    if (previous_root / "implementation-contract.json").exists():
        previous_contract = json.loads(
            (previous_root / "implementation-contract.json").read_bytes()
        )
        for p, h in previous_contract["code_hashes"].items():
            if p not in {"scripts/run_df005.py", "src/kmast/research/domestic_panel.py"}:
                assert digest(Path(p).read_bytes()) == h
        p = "src/kmast/research/domestic_panel.py"
        old_ast = ast.parse((previous_root / "executed-sources" / p).read_bytes())
        new_ast = ast.parse(Path(p).read_bytes())

        def execution_functions(tree):
            return {
                n.name: ast.dump(n)
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name != "window_inputs"
            }

        assert execution_functions(old_ast) == execution_functions(new_ast)
        contract["cache_contract_sha256"] = digest(
            (previous_root / "implementation-contract.json").read_bytes()
        )
        contract["cache_rule_functions_ast_equal"] = True
    immutable_write(TARGET / "implementation-contract.json", canonical(contract))
    immutable_write(Path("artifacts/df005/implementation-contract-v3.json"), canonical(contract))
    seen, jobs, summaries, exclusions = set(), {}, [], []
    scheduled = set()
    with (
        process_lock(TARGET / "research.lock"),
        ProcessPoolExecutor(max_workers=args.workers) as pool,
    ):
        while True:
            manifest = json.loads((SOURCE / "manifest.json").read_bytes())
            if all(i + ":RAW" in manifest["histories"] for i in ("0001", "1001")):
                for symbol in symbols:
                    if symbol in seen or not all(
                        symbol + ":" + basis in manifest["histories"]
                        for basis in ("RAW", "ADJUSTED")
                    ):
                        continue
                    seen.add(symbol)
                    try:
                        raw = load_histories(manifest, symbol, "RAW")
                        adjusted = load_histories(manifest, symbol, "ADJUSTED")
                        index = load_histories(
                            manifest, "0001" if symbol in protocol["kospi"] else "1001", "RAW"
                        )
                        for n, (start, end) in enumerate(WINDOWS, 1):
                            try:
                                stock, benchmark, eligibility = window_inputs(
                                    raw, adjusted, index, start, end
                                )
                            except ValueError as error:
                                exclusions.append(
                                    dict(
                                        symbol=symbol,
                                        window=n,
                                        reason=str(error),
                                        status="DATA_INSUFFICIENT",
                                    )
                                )
                                continue
                            payload = dict(
                                symbol=symbol,
                                window=n,
                                stock=[r.model_dump(mode="json") for r in stock],
                                index=[r.model_dump(mode="json") for r in benchmark],
                                exclusions=[r["date"] for r in calendar["dates"]],
                                eligibility=eligibility,
                            )
                            input_file = TARGET / "inputs" / f"{symbol}-W{n}.json"
                            immutable_write(input_file, canonical(payload))
                            jobs[pool.submit(worker, str(input_file))] = (symbol, n)
                            scheduled.add((symbol, n))
                    except Exception:
                        exclusions.append(
                            dict(
                                symbol=symbol,
                                window="ALL",
                                reason="INPUT_CONFLICT_OR_LINEAGE_HOLD",
                                status="DATA_INSUFFICIENT",
                            )
                        )
            done = [future for future in jobs if future.done()]
            for future in done:
                symbol, n = jobs.pop(future)
                try:
                    summaries.extend(future.result())
                except Exception as error:
                    exclusions.append(
                        dict(
                            symbol=symbol,
                            window=n,
                            reason="REPLAY_OR_ACCOUNTING_FAILED:" + type(error).__name__,
                            status="DATA_INSUFFICIENT",
                        )
                    )
            progress = dict(
                completed_symbol_histories=len(seen),
                scheduled_windows=len(scheduled),
                completed_references=len(summaries),
                pending_windows=len(jobs),
                exclusions=exclusions,
            )
            (TARGET / "progress.json").write_bytes(canonical(progress))
            if not args.watch_collection or len(seen) == 50 or not active_collection():
                for future in as_completed(jobs):
                    symbol, n = jobs[future]
                    try:
                        summaries.extend(future.result())
                    except Exception as error:
                        exclusions.append(
                            dict(
                                symbol=symbol,
                                window=n,
                                reason="REPLAY_OR_ACCOUNTING_FAILED:" + type(error).__name__,
                                status="DATA_INSUFFICIENT",
                            )
                        )
                break
            time.sleep(5)
    final = dict(
        contract=contract,
        summaries=sorted(
            summaries, key=lambda r: (r["symbol"], r["window"], r["scenario"], r["model"])
        ),
        exclusions=exclusions,
        symbols_processed=len(seen),
        references=len(summaries),
        scheduled_windows=len(scheduled),
        original_candidates_unchanged=True,
        order_calls=0,
        cancel_calls=0,
        account_calls=0,
    )
    immutable_write(TARGET / "research-manifest.json", canonical(final))
    print(
        json.dumps({k: final[k] for k in ("symbols_processed", "references", "scheduled_windows")}),
        flush=True,
    )


if __name__ == "__main__":
    main()
