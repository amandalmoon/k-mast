"""Seal exact basic-info queries from the frozen pilot and downloaded official specs."""

import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from kmast.data.krx_acquisition import ENDPOINTS
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest

PUBLIC = Path("artifacts/df009")
PRIVATE = Path("data/data-first-private-df009-sources")


def main():
    raw = (PUBLIC / "DF009_PROTOCOL.json").read_bytes()
    assert raw == subprocess.check_output(
        ["git", "show", "fa0927a:artifacts/df009/DF009_PROTOCOL.json"]
    )
    protocol = json.loads(raw)
    services = {}
    for market, filename in (
        ("KOSPI", "kospi-basic-spec.docx"),
        ("KOSDAQ", "kosdaq-basic-spec.docx"),
    ):
        path = PRIVATE / filename
        with ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
            texts = [
                e.text or ""
                for e in root.findall(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                )
            ]
        urls = [url for text in texts for url in re.findall(r"https://[^\s]+", text)]
        endpoint = "https://data-dbg.krx.co.kr" + ENDPOINTS[market]
        assert endpoint in urls and "basDd" in texts
        fields = [
            "ISU_CD",
            "ISU_SRT_CD",
            "ISU_NM",
            "ISU_ABBRV",
            "LIST_DD",
            "MKT_TP_NM",
            "SECUGRP_NM",
            "KIND_STKCERT_TP_NM",
        ]
        assert all(field in texts for field in fields)
        services[market] = dict(
            endpoint=endpoint,
            api_id=ENDPOINTS[market].rsplit("/", 1)[1],
            source_doc_sha256=digest(path.read_bytes()),
            requested_fields_confirmed=fields,
            version=None,
            version_basis=(
                "Official specification hash and portal modified 2026-01-16; "
                "no semantic version asserted"
            ),
        )
    queries, seen = [], set()
    for target in protocol["targets"]:
        event_day = date.fromisoformat(target["receipt_date"])
        for requested in (event_day, event_day - timedelta(days=1)):
            for market in ("KOSPI", "KOSDAQ"):
                query = dict(market=market, basDd=requested.strftime("%Y%m%d"))
                identity = digest(canonical(query))
                if identity not in seen:
                    queries.append(query)
                    seen.add(identity)
    assert len(queries) <= 48
    plan = dict(
        protocol_sha256=digest(raw),
        services=services,
        queries=queries,
        unique_requests=len(queries),
        maximum_total_requests=len(queries) * 2,
        authentication_issuance_calls=0,
        maximum_attempts_per_query=2,
        wait_after_response_seconds=3.10,
        hard_observed_minimum_seconds=3.05,
        authentication_authorized=False,
        key_path="C:/Users/User/.kmast-readonly/krx.env",
        key_field="KRX_API_KEY",
        header="AUTH_KEY",
        method="GET",
        probe=(
            "First two calls: KOSPI/KOSDAQ event-date basics, within budget; "
            "no public sample key use"
        ),
        private_store="data/data-first-private-df009-krx/",
        documented_daily_key_ceiling=10000,
        data_queries_exclude_prices=True,
        historical_response_success_observed=False,
    )
    atomic_json(PUBLIC / "KRX_QUERY_PLAN.json", plan)
    print(
        json.dumps(
            dict(
                unique_requests=len(queries),
                maximum_total_requests=len(queries) * 2,
                query_plan_sha256=digest(canonical(plan)),
            )
        )
    )


if __name__ == "__main__":
    main()
