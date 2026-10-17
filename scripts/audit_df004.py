"""Compare every pre-existing byte and scan intended public content without printing secrets."""

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.read_kis_env import load_env


def main():
    proof = Path("artifacts/df004")
    baseline = json.loads((proof / "preflight.json").read_bytes())
    allowed = {
        ".github/workflows/ci.yml",
        "scripts/verify.py",
        "README.md",
        "pyproject.toml",
        "requirements-dev.lock",
    }
    changed = []
    for path, sha in baseline["protected_hashes"].items():
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if actual != sha:
            assert path in allowed, "pre-existing protected bytes changed"
            changed.append(path)
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    config_path = Path.home() / ".kmast-readonly/.env"
    config = load_env(config_path)
    secrets = [
        config.app_key.get_secret_value().encode(),
        config.app_secret.get_secret_value().encode(),
    ]
    scanned = 0
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        assert not path.startswith("data/data-first-private"), "private file outside Git exclusion"
        raw = Path(path).read_bytes()
        assert not any(s in raw for s in secrets if s), (
            "credential leak detected; content suppressed"
        )
        scanned += 1
    contract = json.loads((proof / "implementation-contract.json").read_bytes())
    runner = Path("scripts/run_df004.py").read_bytes()
    # Original executing source differed only in line-wrapping a literal to satisfy Ruff.
    wrapped = (
        b"        provenance_limitation=(\n"
        b'            "Initial pages retain sanitized price-field hashes, not wire bytes; "\n'
        b'            "one later wire page preserved. MODP0/1 equality only '
        b'observed on recent100; "\n'
        b'            "provider session/corporate-action policy not independently certified."\n'
        b"        ),"
    )
    original = runner.replace(
        wrapped,
        b'        provenance_limitation="Initial pages retain sanitized price-field '
        b"hashes, not wire bytes; "
        b"one later wire page preserved. MODP0/1 equality only observed on recent100; "
        b'provider session/corporate-action policy not independently certified.",',
    )
    resume = (
        b'    contract_path = proof / "implementation-contract.json"\n'
        b"    if contract_path.exists():\n"
        b"        previous = json.loads(contract_path.read_bytes())\n"
        b'        assert previous["input_hashes"] == contract["input_hashes"]\n'
        b"        assert (\n"
        b'            previous["source_hashes"]["src/kmast/research/ewy.py"]\n'
        b'            == contract["source_hashes"]["src/kmast/research/ewy.py"]\n'
        b"        )\n"
        b"    else:\n"
        b"        immutable_write(contract_path, canonical(contract))"
    )
    original = original.replace(
        resume, b'    immutable_write(proof / "implementation-contract.json", canonical(contract))'
    )
    assert hashlib.sha256(original).hexdigest() == contract["source_hashes"]["scripts/run_df004.py"]
    normalized = runner.replace(
        resume, b'    immutable_write(proof / "implementation-contract.json", canonical(contract))'
    )
    assert ast.dump(ast.parse(original)) == ast.dump(ast.parse(normalized))
    private = Path("data/data-first-private-df004-results")
    assert len(list(private.glob("*.json"))) == 96
    budget = json.loads(Path("data/data-first-private-df004-ewy/budget.json").read_bytes())
    events = [e for e in budget["events"] if "request_time" in e]
    from datetime import datetime

    gaps = [
        (
            datetime.fromisoformat(b["request_time"]) - datetime.fromisoformat(a["request_time"])
        ).total_seconds()
        for a, b in zip(events, events[1:], strict=False)
    ]
    assert budget["requests"] == 9 and budget["auth"] == 2
    report = dict(
        protected_files=len(baseline["protected_hashes"]),
        preexisting_private_files=baseline["private_files"],
        intentional_existing_changes=sorted(changed),
        preserved=True,
        secret_scan_files=scanned,
        secret_leaks=0,
        minimum_observed_request_gap_seconds=min(gaps),
        original_request_spacing_conformant=min(gaps) >= 3,
        spacing_deviation=(
            "2.618ms below3s observed; final collector waits3.05s after response; "
            "no further authentication"
        ),
        protocol_commit="52c0838d5837d3b6116c0165806658b911ef2c64",
        runner_formatting_and_resume_guard_only=True,
        executing_runner_sha256=hashlib.sha256(original).hexdigest(),
        final_runner_sha256=hashlib.sha256(runner).hexdigest(),
        private_result_hashes={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(private.glob("*.json"))
        },
    )
    (proof / "preservation-audit.json").write_bytes(
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    )
    print("DF004 protected source/private bytes, source AST, request limits and secret scan: PASS")


if __name__ == "__main__":
    main()
