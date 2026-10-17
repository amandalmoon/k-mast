"""DF005 response/record lineage, protected bytes, nullable-sector derivative and leak audit."""

import ast
import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from kmast.data.store import DataStore, canonical, digest
from scripts.read_kis_env import load_env


def main():
    proof = Path("artifacts/df005")
    baseline = json.loads((proof / "preflight.json").read_bytes())
    allowed = {"README.md", "scripts/verify.py", ".github/workflows/ci.yml"}
    changes = []
    for path, sha in baseline["protected_hashes"].items():
        if digest(Path(path).read_bytes()) != sha:
            assert path in allowed, "protected pre-existing bytes changed"
            changes.append(path)
    old = ast.parse(Path("src/kmast/research/attribution.py").read_bytes())
    new = ast.parse(Path("src/kmast/research/panel_attribution.py").read_bytes())

    class RestoreLookup(ast.NodeTransformer):
        count = 0

        def visit_Call(self, node):
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sector"
                and node.func.attr == "get"
            ):
                self.count += 1
                return ast.Subscript(value=node.func.value, slice=node.args[0], ctx=ast.Load())
            return self.generic_visit(node)

    transformer = RestoreLookup()
    new = transformer.visit(new)
    old.body = old.body[1:]
    new.body = new.body[1:]
    assert transformer.count == 1 and ast.dump(new) == ast.dump(old)
    folder = Path("data/data-first-private-df005-panel")
    budget = json.loads((folder / "budget.json").read_bytes())
    assert (
        budget["requests"] == 803
        and budget["authentication"] == 1
        and not budget["response_pending"]
    )
    assert len(budget["events"]) == 803
    wire_pages = 0
    for e in budget["events"]:
        assert json.loads((folder / "events" / f"{e['sequence']:04}.json").read_bytes()) == e
        if e["kind"] == "AUTH":
            assert e["body_status"] == "SENSITIVE_HASH_ONLY" and "wire_path" not in e
        else:
            assert digest((folder / e["wire_path"]).read_bytes()) == e["wire_sha256"]
            assert (
                digest((folder / "canonical" / (e["canonical_sha256"] + ".json")).read_bytes())
                == e["canonical_sha256"]
            )
            wire_pages += 1
    gaps = [
        (
            datetime.fromisoformat(b["request_time"]) - datetime.fromisoformat(a["received_at"])
        ).total_seconds()
        for a, b in zip(budget["events"], budget["events"][1:], strict=False)
    ]
    assert min(gaps) >= 3.05
    manifest = json.loads((folder / "manifest.json").read_bytes())
    store = DataStore(folder)
    distinct = defaultdict(dict)
    row_count = 0
    for identity, page in manifest["pages"].items():
        cached = store.cached(identity)
        assert cached is not None and cached["metadata"]["source_hash"] == page["source_hash"]
        rows = store.load_dataset(page["dataset_id"])
        assert (
            digest(canonical([r.model_dump(mode="json") for r in rows])) == page["normalized_hash"]
        )
        link = json.loads(
            (folder / "lineage" / (digest(canonical(identity)) + ".json")).read_bytes()
        )
        assert link["canonical_sha256"] == page["source_hash"]
        for row in rows:
            assert (
                digest(canonical(row.model_dump(mode="json")))
                == page["record_hashes"][row.record_id]
            )
            assert row.source_hash == page["source_hash"] and row.received_at == row.acquired_at
            assert row.quality_flags and row.event_time is None
            row_count += 1
            key = (row.symbol, row.price_basis)
            projection = tuple(
                str(v) for v in (row.open, row.high, row.low, row.close, row.volume, row.turnover)
            )
            if row.exchange_date in distinct[key]:
                assert distinct[key][row.exchange_date] == projection
            distinct[key][row.exchange_date] = projection
    cfg = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = [cfg.app_key.get_secret_value().encode(), cfg.app_secret.get_secret_value().encode()]
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    scanned = 0
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        assert not path.startswith("data/"), "private acquisition outside Git exclusion"
        assert not any(s in Path(path).read_bytes() for s in secrets if s), (
            "secret detected, content suppressed"
        )
        scanned += 1
    symbols = []
    protocol = json.loads((proof / "DF005_PROTOCOL.json").read_bytes())
    for market in ("kospi", "kosdaq"):
        for symbol in protocol[market]:
            dates = sorted(distinct[symbol, "RAW"])
            symbols.append(
                dict(
                    symbol=symbol,
                    market=market,
                    raw_dates=len(dates),
                    adjusted_dates=len(distinct[symbol, "ADJUSTED"]),
                    start=str(dates[0]) if dates else None,
                    end=str(dates[-1]) if dates else None,
                    selection="CURRENT_SURVIVOR_STOCK_HEURISTIC_NOT_PIT",
                )
            )
    report = dict(
        protected_files=len(baseline["protected_hashes"]),
        private_files=baseline["private_files"],
        intentional_changes=sorted(changes),
        preserved=True,
        secret_scan_files=scanned,
        secret_leaks=0,
        derivative_only_nullable_sector_lookup=True,
        requests=803,
        authentication=1,
        minimum_response_complete_to_request_seconds=min(gaps),
        wire_market_responses_retained=wire_pages,
        auth_response_bytes_withheld=1,
        normalized_page_rows=row_count,
        unique_stock_raw_rows=sum(
            len(v) for (s, b), v in distinct.items() if len(s) == 6 and b == "RAW"
        ),
        unique_stock_adjusted_rows=sum(
            len(v) for (s, b), v in distinct.items() if len(s) == 6 and b == "ADJUSTED"
        ),
        unique_index_rows=sum(len(v) for (s, b), v in distinct.items() if len(s) == 4),
        stocks_with_observations=sum(s["raw_dates"] > 0 for s in symbols),
        symbols=symbols,
        pit_universe=False,
        delisting_history=False,
        halt_event_history=False,
        corporate_action_history=False,
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        live_authentication=0,
    )
    v2 = Path("data/data-first-private-df005-replays-v2")
    v3 = Path("data/data-first-private-df005-replays-v3")
    if (v3 / "research-manifest.json").exists():
        latest = json.loads((v3 / "implementation-contract.json").read_bytes())
        for p, h in latest["code_hashes"].items():
            assert digest(Path(p).read_bytes()) == h
        p = "src/kmast/research/domestic_panel.py"
        previous = (v2 / "executed-sources" / p).read_text(encoding="utf-8")
        final = Path(p).read_text(encoding="utf-8")
        assert final.count("if factor_change > D(0):") == 1
        restored = final.replace("if factor_change > D(0):", 'if factor_change > D(".001"):')
        assert ast.dump(ast.parse(previous)) == ast.dump(ast.parse(restored))
        matches = 0
        for path in (v3 / "references").glob("*.json"):
            assert digest(path.read_bytes()) == digest((v2 / "references" / path.name).read_bytes())
            matches += 1
        assert matches == 1770
        report.update(
            qualified_cache_exact_matches=matches,
            execution_functions_unchanged=True,
            eligibility_only_tightened_to_zero=True,
        )
    (proof / "collection-and-preservation-audit.json").write_bytes(
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    )
    print(
        "DF005 protected bytes,802 wire responses, normalized lineage, timing and secret scan: PASS"
    )


if __name__ == "__main__":
    main()
