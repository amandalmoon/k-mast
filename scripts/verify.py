"""Run local checks and retain byte-exact subprocess output; no broker/network operations."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--milestone",
        choices=(
            "km000",
            "km001",
            "km002",
            "km003",
            "km004",
            "km005",
            "km005r1",
            "data-first",
            "df002",
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
            "df016",
            "df017",
            "df017r1",
            "df017r2",
            "gcp-seoul",
        ),
        default="km000",
    )
    args = parser.parse_args()
    evidence = ROOT / "artifacts" / args.milestone
    evidence.mkdir(parents=True, exist_ok=True)
    checks = {
        "pytest": ["-m", "pytest", "-q", f"--junitxml=artifacts/{args.milestone}/junit.xml"],
        "ruff": ["-m", "ruff", "check", "."],
        "format": ["-m", "ruff", "format", "--check", "."],
        "mypy": ["-m", "mypy", "src"],
        "build": ["-m", "build", "--no-isolation"],
        "demo": ["-m", "kmast.demo"],
    }
    if args.milestone == "km001":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
        ]
        checks["data-demo"] = [
            "-m",
            "kmast.data.cli",
            "fixture",
            "--output",
            "artifacts/km001/fixture-data-v1",
        ]
    if args.milestone == "km002":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
            "tests/test_km001.py",
            "tests/test_km001_edges.py",
        ]
        checks["mock-demo"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["mock-replay"] = checks["mock-demo"].copy()
        checks["independent-accounting"] = [
            "scripts/check_km002_evidence.py",
            "artifacts/km002/scenarios-v2",
        ]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km002.py"]
    if args.milestone == "km003":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
            "tests/test_km001.py",
            "tests/test_km001_edges.py",
            "tests/test_km002.py",
            "tests/test_km002_edges.py",
        ]
        checks["alpha-functional"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["alpha-replay"] = checks["alpha-functional"].copy()
        checks["independent-reference"] = [
            "scripts/check_km003_evidence.py",
            "artifacts/km003/functional-v1",
        ]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km003.py"]
    if args.milestone == "km004":
        checks["risk-diagnostic"] = ["scripts/risk_diagnostic_km004.py"]
        checks["regression220"] = [
            "-m",
            "pytest",
            "-q",
            "--ignore=tests/test_km004.py",
            "--ignore=tests/test_km004_edges.py",
        ]
        checks["joint-demo"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["joint-replay"] = checks["joint-demo"].copy()
        checks["independent-accounting"] = ["scripts/check_km004_evidence.py"]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km004.py"]
        checks["old-mock-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["old-alpha-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
    if args.milestone == "km005":
        checks["regression252"] = ["-m", "pytest", "-q", "--ignore=tests/test_km005.py"]
        checks["km005-new"] = ["-m", "pytest", "-q", "tests/test_km005.py"]
        checks["data-absent-hold"] = [
            "-m",
            "kmast.research.cli",
            "--output",
            "artifacts/km005/offline",
        ]
        checks["km002-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["km003-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["km004-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["economic-evidence"] = ["scripts/check_km005_evidence.py"]
    if args.milestone == "km005r1":
        checks["regression285"] = ["-m", "pytest", "-q", "--ignore=tests/test_km005r1.py"]
        checks["new-rights-contracts"] = ["-m", "pytest", "-q", "tests/test_km005r1.py"]
        checks["km002-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["km003-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["km004-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["data-absent-hold"] = [
            "-m",
            "kmast.research.cli",
            "--output",
            "artifacts/km005r1/offline",
        ]
        checks["economic-evidence"] = [
            "scripts/check_km005_evidence.py",
            "--report",
            "artifacts/km005r1/offline/qualification.json",
        ]
    if args.milestone == "data-first":
        checks["regression296"] = ["-m", "pytest", "-q", "--ignore=tests/test_data_first.py"]
        checks["new-exploratory-contracts"] = ["-m", "pytest", "-q", "tests/test_data_first.py"]
        checks["km002-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["km003-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["km004-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["independent-exploration"] = ["scripts/check_data_first_evidence.py"]
    if args.milestone == "df002":
        checks["regression312"] = ["-m", "pytest", "-q", "--ignore=tests/test_df002.py"]
        checks["causal-new"] = ["-m", "pytest", "-q", "tests/test_df002.py"]
        checks["oms-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/df002/oms-replay",
        ]
        checks["oms-independent"] = [
            "scripts/check_km002_evidence.py",
            "artifacts/df002/oms-replay",
        ]
        checks["alpha-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/df002/alpha-replay",
        ]
        checks["alpha-independent"] = [
            "scripts/check_km003_evidence.py",
            "artifacts/df002/alpha-replay",
        ]
        checks["joint-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/df002/joint-replay",
        ]
        checks["previous-exploratory"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
    if args.milestone == "df003":
        checks["regression331"] = ["-m", "pytest", "-q", "--ignore=tests/test_df003.py"]
        checks["new-hypothesis-controls"] = ["-m", "pytest", "-q", "tests/test_df003.py"]
        checks["oms-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/df003/oms-replay",
        ]
        checks["oms-independent"] = [
            "scripts/check_km002_evidence.py",
            "artifacts/df003/oms-replay",
        ]
        checks["alpha-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/df003/alpha-replay",
        ]
        checks["alpha-independent"] = [
            "scripts/check_km003_evidence.py",
            "artifacts/df003/alpha-replay",
        ]
        checks["joint-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/df003/joint-replay",
        ]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        checks["hypothesis-independent"] = ["scripts/check_df003_evidence.py", "--private"]
    if args.milestone == "df004":
        checks["regression354"] = ["-m", "pytest", "-q", "--ignore=tests/test_df004.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df004/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        checks["df003-independent"] = ["scripts/check_df003_evidence.py", "--private"]
        checks["ewy-independent"] = ["scripts/check_df004_evidence.py", "--private"]
        checks["preservation-secret-audit"] = ["-m", "scripts.audit_df004"]
    if args.milestone == "df005":
        checks["regression386"] = ["-m", "pytest", "-q", "--ignore=tests/test_df005.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df005/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        checks["df003-independent"] = ["scripts/check_df003_evidence.py", "--private"]
        checks["df004-independent"] = ["scripts/check_df004_evidence.py", "--private"]
        checks["panel-independent"] = ["scripts/check_df005_evidence.py", "--private"]
        checks["lineage-preservation-secrets"] = ["-m", "scripts.audit_df005"]
    if args.milestone == "df006":
        checks["regression413"] = ["-m", "pytest", "-q", "--ignore=tests/test_df006.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df006/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        checks["df003-independent"] = ["scripts/check_df003_evidence.py", "--private"]
        checks["df004-independent"] = ["scripts/check_df004_evidence.py", "--private"]
        checks["df005-independent"] = ["scripts/check_df005_evidence.py", "--private"]
        checks["df006-private-audit"] = ["-m", "scripts.audit_df006"]
        checks["df006-independent"] = ["scripts/check_df006_evidence.py", "--private"]
    if args.milestone == "df007":
        checks["regression433"] = ["-m", "pytest", "-q", "--ignore=tests/test_df007.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df007/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in ("df003", "df004", "df005", "df006"):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df007-preservation"] = ["-m", "scripts.audit_df007"]
        checks["df007-independent"] = ["scripts/check_df007_evidence.py", "--private"]
    if args.milestone == "df008":
        checks["regression450"] = ["-m", "pytest", "-q", "--ignore=tests/test_df008.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df008/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in ("df003", "df004", "df005", "df006", "df007"):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df008-preservation"] = ["-m", "scripts.audit_df008"]
        checks["df008-independent"] = ["scripts/check_df008_evidence.py", "--private"]
    if args.milestone == "df009":
        checks["regression471"] = ["-m", "pytest", "-q", "--ignore=tests/test_df009.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df009/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in ("df003", "df004", "df005", "df006", "df007", "df008"):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df009-preservation"] = ["-m", "scripts.audit_df009"]
        checks["df009-independent"] = ["scripts/check_df009_evidence.py", "--private"]
    if args.milestone == "df009r1":
        checks["regression486"] = ["-m", "pytest", "-q", "--ignore=tests/test_df009_resume.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df009r1/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in ("df003", "df004", "df005", "df006", "df007", "df008", "df009"):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df009r1-preservation"] = ["-m", "scripts.audit_df009r1"]
        checks["df009r1-independent"] = ["scripts/check_df009r1_evidence.py", "--private"]
    if args.milestone == "df010":
        checks["regression492"] = ["-m", "pytest", "-q", "--ignore=tests/test_df010.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df010/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in ("df003", "df004", "df005", "df006", "df007", "df008", "df009", "df009r1"):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df010-preservation"] = ["-m", "scripts.audit_df010"]
        checks["df010-independent"] = ["scripts/check_df010_evidence.py", "--private"]
    if args.milestone == "df011":
        checks["regression504"] = ["-m", "pytest", "-q", "--ignore=tests/test_df011.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df011/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df011-preservation"] = ["-m", "scripts.audit_df011"]
        checks["df011-independent"] = ["scripts/check_df011_evidence.py", "--private"]
    if args.milestone == "df012":
        checks["regression520"] = ["-m", "pytest", "-q", "--ignore=tests/test_df012.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df012/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df012-preservation"] = ["-m", "scripts.audit_df012"]
        checks["df012-independent"] = ["scripts/check_df012_evidence.py", "--private"]
    if args.milestone == "df013":
        checks["regression537"] = ["-m", "pytest", "-q", "--ignore=tests/test_df013.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df013/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df013-cached-readiness"] = ["-m", "scripts.evaluate_df013"]
        checks["df013-official-schema"] = ["-m", "scripts.assess_df013_supply"]
        checks["df013-synthetic"] = ["-m", "scripts.replay_df013"]
        checks["df013-aggregate"] = ["-m", "scripts.finalize_df013"]
        checks["df013-preservation"] = ["-m", "scripts.audit_df013"]
        checks["df013-independent"] = ["scripts/check_df013_evidence.py", "--private"]
    if args.milestone == "df014":
        checks["regression573"] = ["-m", "pytest", "-q", "--ignore=tests/test_df014.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df014/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df014-preflight-offline"] = ["-m", "scripts.preflight_df014"]
        checks["df014-report"] = ["-m", "scripts.report_df014"]
        checks["df014-preservation"] = ["-m", "scripts.audit_df014"]
        checks["df014-independent"] = ["scripts/check_df014_evidence.py", "--private"]
    if args.milestone == "df015":
        checks["regression608"] = ["-m", "pytest", "-q", "--ignore=tests/test_df015.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df015/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df015-offline-stress"] = ["-m", "scripts.stress_df015"]
        checks["df015-cached-report"] = ["-m", "scripts.report_df015"]
        checks["df015-preservation"] = ["-m", "scripts.audit_df015"]
        checks["df015-independent"] = ["scripts/check_df015_evidence.py", "--private"]
    if args.milestone == "df016":
        checks["regression637"] = ["-m", "pytest", "-q", "--ignore=tests/test_df016.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df016/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df016-causal-replay"] = ["-m", "scripts.replay_df016"]
        checks["df016-official-assessment"] = ["-m", "scripts.assess_df016"]
        checks["df016-preservation"] = ["-m", "scripts.audit_df016"]
        checks["df016-independent"] = ["scripts/check_df016_evidence.py", "--private"]
    if args.milestone == "df017":
        checks["regression685"] = ["-m", "pytest", "-q", "--ignore=tests/test_df017.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df017/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
            "df016",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df017-synthetic-engine"] = ["-m", "scripts.replay_df017"]
        checks["df017-report"] = ["-m", "scripts.report_df017"]
        checks["df017-preservation"] = ["-m", "scripts.audit_df017"]
        checks["df017-independent"] = ["scripts/check_df017_evidence.py", "--private"]
    if args.milestone == "df017r1":
        checks["regression735"] = ["-m", "pytest", "-q", "--ignore=tests/test_df017r1.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df017r1/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
            "df016",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df017-independent"] = ["scripts/check_df017_evidence.py", "--private"]
        checks["df017r1-preservation"] = ["-m", "scripts.audit_df017r1"]
        checks["df017r1-independent"] = ["scripts/check_df017r1_evidence.py"]
    if args.milestone == "df017r2":
        checks["regression735"] = ["-m", "pytest", "-q", "--ignore=tests/test_df017r2.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/df017r2/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
            "df016",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df017-independent"] = ["scripts/check_df017_evidence.py", "--private"]
        checks["df017r1-independent"] = ["scripts/check_df017r1_evidence.py"]
        checks["df017r2-preservation"] = ["-m", "scripts.audit_df017r2"]
        checks["df017r2-independent"] = ["scripts/check_df017r2_evidence.py", "--private"]
    if args.milestone == "gcp-seoul":
        checks["regression735"] = ["-m", "pytest", "-q", "--ignore=tests/test_gcp_seoul.py"]
        for label, module, checker in (
            ("oms", "kmast.execution.demo", "scripts/check_km002_evidence.py"),
            ("alpha", "kmast.simulation.cli", "scripts/check_km003_evidence.py"),
            ("joint", "kmast.portfolio.demo", None),
        ):
            output = "artifacts/gcp-seoul/" + label + "-replay"
            checks[label + "-replay"] = ["-m", module, "--output", output]
            if checker:
                checks[label + "-independent"] = [checker, output]
        checks["v2-independent"] = ["scripts/check_data_first_evidence.py", "--private"]
        checks["v3-independent"] = ["scripts/check_df002_evidence.py", "--private"]
        for prior in (
            "df003",
            "df004",
            "df005",
            "df006",
            "df007",
            "df008",
            "df009",
            "df009r1",
            "df010",
            "df011",
            "df012",
            "df013",
            "df014",
            "df015",
            "df016",
        ):
            checks[prior + "-independent"] = [
                "scripts/check_" + prior + "_evidence.py",
                "--private",
            ]
        checks["df017-independent"] = ["scripts/check_df017_evidence.py", "--private"]
        checks["df017r1-independent"] = ["scripts/check_df017r1_evidence.py"]
        checks["df017r2-independent"] = ["scripts/check_df017r2_evidence.py", "--private"]
        checks["gcp-seoul-cost-model"] = ["scripts/report_gcp_seoul.py", "--check"]
        checks["gcp-seoul-preservation"] = ["-m", "scripts.audit_gcp_seoul"]
        checks["gcp-seoul-independent"] = ["scripts/check_gcp_seoul_evidence.py", "--private"]
    results = []
    for name, args in checks.items():
        result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True)
        for stream, payload in (("stdout", result.stdout), ("stderr", result.stderr)):
            if evidence.name in {
                "df002",
                "df003",
                "df004",
                "df005",
                "df006",
                "df007",
                "df008",
                "df009",
                "df009r1",
                "df010",
                "df011",
                "df012",
                "df013",
                "df014",
                "df015",
                "df016",
                "df017",
                "df017r1",
                "df017r2",
                "gcp-seoul",
            }:
                private_logs = (
                    ROOT / "data/data-first-private-market-v1" / (evidence.name + "-check-logs")
                )
                if evidence.name == "df005":
                    private_logs = ROOT / "data/data-first-private-df005-check-logs"
                if evidence.name == "df006":
                    private_logs = ROOT / "data/data-first-private-df006-check-logs"
                if evidence.name == "df007":
                    private_logs = ROOT / "data/data-first-private-df007-check-logs"
                if evidence.name == "df008":
                    private_logs = ROOT / "data/data-first-private-df008-check-logs"
                if evidence.name == "df009":
                    private_logs = ROOT / "data/data-first-private-df009-check-logs"
                if evidence.name == "df009r1":
                    private_logs = ROOT / "data/data-first-private-df009r1-check-logs"
                if evidence.name == "df010":
                    private_logs = ROOT / "data/data-first-private-df010-check-logs"
                if evidence.name == "df011":
                    private_logs = ROOT / "data/data-first-private-df011-check-logs"
                if evidence.name == "df012":
                    private_logs = ROOT / "data/data-first-private-df012-check-logs"
                if evidence.name == "df013":
                    private_logs = ROOT / "data/data-first-private-df013-check-logs"
                if evidence.name == "df014":
                    private_logs = ROOT / "data/data-first-private-df014-check-logs"
                if evidence.name == "df015":
                    private_logs = ROOT / "data/data-first-private-df015-check-logs"
                if evidence.name == "df016":
                    private_logs = ROOT / "data/data-first-private-df016-check-logs"
                if evidence.name == "df017":
                    private_logs = ROOT / "data/data-first-private-df017-check-logs"
                if evidence.name == "df017r1":
                    private_logs = ROOT / "data/data-first-private-df017r1-check-logs"
                if evidence.name == "df017r2":
                    private_logs = ROOT / "data/data-first-private-df017r2-check-logs"
                if evidence.name == "gcp-seoul":
                    private_logs = ROOT / "data/data-first-private-gcp-seoul-check-logs"
                private_logs.mkdir(parents=True, exist_ok=True)
                (private_logs / f"{name}.{stream}.log").write_bytes(payload)
                payload = (
                    "\n".join(line.rstrip() for line in payload.decode("utf-8").splitlines())
                    + ("\n" if payload else "")
                ).encode("utf-8")
            (evidence / f"{name}.{stream}.log").write_bytes(payload)
        results.append(
            {
                "name": name,
                "command": [sys.executable, *args],
                "exit_code": result.returncode,
                "status": "PASS" if result.returncode == 0 else "FAIL",
            }
        )
        print(f"{name}: {results[-1]['status']}")
    (evidence / "checks.json").write_bytes((json.dumps(results, indent=2) + "\n").encode("utf-8"))
    sys.exit(int(any(r["exit_code"] != 0 for r in results)))


if __name__ == "__main__":
    main()
