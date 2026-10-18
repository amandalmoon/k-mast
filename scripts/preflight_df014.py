"""Public documentation and local read-only checks; no KIS authentication or sockets."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import yaml

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-public-docs", action="store_true")
    args = parser.parse_args()
    private = Path("data/data-first-private-df014-sources")
    sha = "2077773a69a428daf63e148182511f068cc45de3"
    url = f"https://raw.githubusercontent.com/koreainvestment/open-trading-api/{sha}/kis_devlp.yaml"
    previous = Path("artifacts/df014/preflight.json")
    if args.refresh_public_docs or not previous.exists():
        raw = urlopen(
            Request(url, headers={"User-Agent": "K-MAST official endpoint review"}), timeout=30
        ).read()
    else:
        cached_hash = json.loads(previous.read_bytes())["source"]["sha256"]
        raw = (private / "raw" / (cached_hash + ".bin")).read_bytes()
        assert digest(raw) == cached_hash
    immutable_write(private / "raw" / (digest(raw) + ".bin"), raw)
    documented = yaml.safe_load(raw)
    assert documented["vops"] == "ws://ops.koreainvestment.com:31000"
    assert documented["vps"] == "https://openapivts.koreainvestment.com:29443"
    prior = json.loads(Path("artifacts/df013/supply-assessment.json").read_bytes())
    assert all(r["demo_branch_documented"] for r in prior["schemas"].values())
    masters = []
    for market, code in [("kospi", "073240"), ("kosdaq", "462860")]:
        path = Path("data/data-first-private-market-v1") / (market + "-master.json")
        contents = path.read_bytes()
        rows = [r for r in json.loads(contents) if r["symbol"] == code]
        assert len(rows) == 1
        masters.append(
            dict(
                symbol=code,
                market=market.upper(),
                isin=rows[0]["isin"],
                cached_master_sha256=digest(contents),
                current_pilot_day_status_verified=False,
                halt_status=None,
            )
        )
    try:
        clock = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, timeout=10)
        clock_result = dict(
            command="w32tm /query /status",
            exit_code=clock.returncode,
            stdout_sha256=digest(clock.stdout),
            stderr_sha256=digest(clock.stderr),
        )
    except (OSError, subprocess.TimeoutExpired):
        clock_result = dict(command="w32tm /query /status", exit_code=None)
    # A local status query alone supplies no independently measured offset bound.
    result = dict(
        status="DF014_PILOT_PENDING_APPROVAL",
        assessed_at=datetime.now(UTC).isoformat(),
        protocol_sha256=digest(Path("artifacts/df014/DF014_PROTOCOL.json").read_bytes()),
        source=dict(url=url, repository_commit=sha, sha256=digest(raw)),
        official_paper_endpoint=documented["vops"],
        official_auth_root=documented["vps"],
        endpoint_reconfirmed=True,
        encryption="NONE_ON_WS_TRANSPORT",
        approval_key_transmitted_in_ws_header=True,
        transport_protection_verified=False,
        no_speculative_wss_or_host_test=True,
        clock_status=clock_result,
        clock_sync_verified=False,
        clock_error_bound_seconds=None,
        security_membership_diagnostics=masters,
        pilot_day_security_status=None,
        exact_krx_session_calendar_verified=False,
        regular_open_for_pilot_verified=False,
        documented_paper_demo_branches=True,
        actual_paper_entitlement=None,
        actual_four_subscription_capacity=None,
        first_subscription_time=None,
        provider_fee=None,
        additional_rights_required=None,
        terms_source="https://apiportal.koreainvestment.com/about-howto",
        terms_scope=(
            "General API usage guidance does not certify this key, plaintext protection, "
            "pricing, or extra data-retention rights"
        ),
        venue_scope="KRX channels only; not NXT or consolidated VWAP/volume",
        human_streaming_approval_record_present=False,
        authentication_attempts=0,
        websocket_connections=0,
        actual_subscriptions=0,
        scheduled_execution=False,
        prerequisites=[
            "Exact new human approval",
            "Protected transport evidence for official plaintext endpoint",
            "PAPER approval/four-channel entitlement/hours/terms evidence",
            "Current two-security status and exact exchange session evidence",
        ],
    )
    atomic_json(Path("artifacts/df014/preflight.json"), result)
    print(
        "DF014 official plaintext PAPER endpoint reconfirmed; auth/socket calls 0, "
        "approval/security prerequisites pending"
    )


if __name__ == "__main__":
    main()
