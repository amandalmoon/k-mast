"""Inspect pinned official sample AST without importing or executing upstream code."""

import ast
import json
from pathlib import Path

from kmast.data.orb_observation import COLUMNS
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest


def main():
    source = Path("data/data-first-private-df013-sources")
    manifest = json.loads((source / "manifest.json").read_bytes())
    texts = {}
    for path, record in manifest.items():
        raw = (source / "raw" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        texts[path] = raw.decode("utf-8")
    text = texts["examples_user/domestic_stock/domestic_stock_functions_ws.py"]
    tree = ast.parse(text)
    schemas = {}
    for name, channel in [("ccnl_krx", "H0STCNT0"), ("asking_price_krx", "H0STASP0")]:
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assignment = next(
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "columns" for t in n.targets)
        )
        columns = ast.literal_eval(assignment.value)
        assert columns == COLUMNS[channel]
        segment = ast.get_source_segment(text, node)
        assert 'env_dv == "demo"' in segment and 'tr_id = "' + channel + '"' in segment
        schemas[channel] = dict(
            fields=columns,
            field_count=len(columns),
            demo_branch_documented=True,
            actual_entitlement_verified=False,
            source_function=name,
        )
    auth = texts["examples_user/kis_auth.py"]
    assert "/oauth2/Approval" in auth and 'svr == "vps"' in auth and 'p["secretkey"]' in auth
    atomic_json(
        Path("artifacts/df013/supply-assessment.json"),
        dict(
            status="DOCUMENTED_SAMPLE_SUPPORT_ACTUAL_ENTITLEMENT_UNKNOWN",
            sources=manifest,
            schemas=schemas,
            upstream_code_executed=False,
            symbol_field_mapping=(
                "Protocol trade symbol label STCK_SHRN_ISCD maps to actual "
                "MKSC_SHRN_ISCD; protocol preserved, exact wire schema used"
            ),
            paper_demo_branches_present=True,
            real_fallback_allowed=False,
            actual_approval_calls=0,
            actual_connections=0,
            actual_subscriptions=0,
            subscription_limit_verified=None,
            actual_paper_permission=None,
            cost=None,
            historical_book_depth_coverage=None,
            actual_start_availability=None,
            trade_business_date_field="BSOP_DATE",
            quote_business_date_field=None,
            correction_cancel_unique_id=None,
            provider_message_sequence=None,
            market_status_policy=(
                "Retain "
                "HOUR_CLS_CODE/NEW_MKOP_CLS_CODE/MARKET_CLS_CODE/TRHT_YN/VI_STND_PRC; "
                "do not infer full halt/VI/resumption or continuous auction state "
                "from field presence"
            ),
            source_license_policy=(
                "Schema facts and hashes referenced; no upstream implementation redistribution"
            ),
        ),
    )
    print(
        "DF013 pinned official schema 47/63 fields and demo branches verified; "
        "access remains untested"
    )


if __name__ == "__main__":
    main()
