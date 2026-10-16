"""Independent hold/metric/provenance checks without importing trading code."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", type=Path, default=Path("artifacts/km005/offline/qualification.json")
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    assert report["status"] == "KM005_DATA_HOLD"
    assert report["gates"]["G2"] == "NOT_EXECUTED"
    assert report["gates"]["economic_status"] == "ECON_NOT_EXECUTED"
    assert report["gates"]["live_status"] == "LIVE_NOT_APPROVED"
    assert report["calculation_mode"] == "NOT_EXECUTED"
    assert all(value is None for value in report["metrics"].values())
    assert all(
        report[k] == 0
        for k in (
            "kis_auth_calls",
            "market_calls",
            "account_calls",
            "actual_orders",
            "actual_cancels",
        )
    )
    q = report["quality"]
    if report["data_access"] == "LOCAL_VERIFIED":
        assert q["real_rows"] == 180 and q["unique_stock_days"] == 60
        assert q["synthetic_rows"] == 0 and report["raw_alpha_adapter_rejections"] == 60
    else:
        assert q["total_rows"] == 0
    assert q["missing_rate"] is None and not q["expected_grid_verified"]
    assert not report["license_scope"]["applicable_agreement_ref"]
    print("Independent economic HOLD and publication metadata audit: PASS")


if __name__ == "__main__":
    main()
