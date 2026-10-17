"""Approved exact-allowlist document acquisition; no KIS or economic replay."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from kmast.data.document_acquisition import DocumentWire
from kmast.data.document_qualification import qualify_document
from kmast.data.panel_acquisition import atomic_json, immutable_write, process_lock
from kmast.data.store import canonical, digest
from scripts.collect_df006 import load_key

FOLDER = Path("data/data-first-private-df008-documents")


def source_gate():
    source = Path("data/data-first-private-df006-events")
    manifest = json.loads((source / "manifest.json").read_bytes())
    assert len(manifest["pages"]) == 210 and len(manifest["documents"]) == 2
    assert json.loads((source / "budget.json").read_bytes())["used"] == 212
    unique = {}
    for record in manifest["pages"].values():
        raw = (source / "wire" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        for row in json.loads(raw)["list"]:
            receipt = row["rcept_no"]
            assert receipt not in unique or unique[receipt] == row
            unique[receipt] = row
    assert len(unique) == 19319
    normalized = json.loads(
        Path("data/data-first-private-df007-census-v2/all-normalized-disclosures.json").read_bytes()
    )["records"]
    originals = [r for r in normalized if r["family"] == "D1" and r["revision"] == "ORIGINAL"]
    revisions = [r for r in normalized if r["family"] == "D1" and r["revision"] == "CORRECTION"]
    assert len(originals) == 620 and len(revisions) == 130
    selected = json.loads((source / "selected-disclosures.json").read_bytes())["rows"]
    assert len(selected) == 302
    assert all(unique[k] == r["row"] for k, r in selected.items())
    for receipt, record in manifest["documents"].items():
        raw = (source / "wire" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        parsed = qualify_document(raw, receipt, unique[receipt]["corp_code"])
        assert parsed["DOCUMENT_VERIFIED"]
    return dict(pages=210, unique=19319, originals=620, revisions=130, old50=302, controls=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    files = ["artifacts/df008/DF008_PROTOCOL.json", "artifacts/df008/document-targets.json"]
    for name in files:
        assert Path(name).read_bytes() == subprocess.check_output(
            ["git", "show", "bd3325f:" + name]
        )
    targets = json.loads(Path(files[1]).read_bytes())
    scope = digest(canonical({name: digest(Path(name).read_bytes()) for name in files}))
    ordered = sorted(targets["originals"], key=lambda r: r["rank_sha256"]) + sorted(
        targets["revisions"], key=lambda r: r["rank_sha256"]
    )
    assert len(ordered) == 89 and len(targets["originals"]) == 60
    with process_lock(FOLDER / "collector.lock"):
        atomic_json(FOLDER / "source-gate.json", source_gate())
        # Store the exact executing source, before any authenticated call.
        sources = [
            "scripts/collect_df008.py",
            "src/kmast/data/document_acquisition.py",
            "src/kmast/data/document_qualification.py",
        ]
        source_hashes = {}
        for name in sources:
            raw = Path(name).read_bytes()
            source_hashes[name] = digest(raw)
            immutable_write(FOLDER / "executed-sources" / name, raw)
        atomic_json(FOLDER / "executed-source-hashes.json", source_hashes)
        key = (
            load_key(Path("C:/Users/User/.kmast-readonly/opendart.env"))
            if args.execute_approved
            else ""
        )
        wire = DocumentWire(
            FOLDER, tuple(r["receipt"] for r in ordered), scope, key, enabled=args.execute_approved
        )
        if args.execute_approved:
            immutable_write(
                FOLDER / "approval.json",
                canonical(
                    dict(
                        scope_sha256=scope,
                        maximum_requests=178,
                        source="Explicit human approval in this chat",
                        authentication_calls=0,
                    )
                ),
            )
        evidence = []
        for index, target in enumerate(ordered[:2] if args.probe_only else ordered):
            record = wire.get(target["receipt"])
            parsed = None
            if record["success"]:
                raw = (FOLDER / "wire" / (record["sha256"] + ".bin")).read_bytes()
                parsed = qualify_document(raw, target["receipt"], target["corp_code"])
                immutable_write(
                    FOLDER / "qualified" / (target["receipt"] + ".json"), canonical(parsed)
                )
            evidence.append(parsed)
            print(
                json.dumps(
                    dict(
                        completed=index + 1,
                        used=wire.state["used"],
                        safe_zip=record["success"],
                        parsed=bool(parsed and parsed["DOCUMENT_VERIFIED"]),
                    )
                ),
                flush=True,
            )
            if index == 9:
                zips = sum(bool(wire.cached(r["receipt"])["success"]) for r in ordered[:10])
                parsed_count = sum(bool(r and r["DOCUMENT_VERIFIED"]) for r in evidence)
                corp_count = sum(bool(r and r["CORPORATE_IDENTITY_VERIFIED"]) for r in evidence)
                if zips < 8 or parsed_count < 7 or corp_count < 6:
                    atomic_json(
                        FOLDER / "early-stop.json",
                        dict(
                            reason="FROZEN_FIRST10_THRESHOLD",
                            safe_zip=zips,
                            parsed=parsed_count,
                            corporations=corp_count,
                            at=datetime.now(UTC).isoformat(),
                        ),
                    )
                    return


if __name__ == "__main__":
    main()
