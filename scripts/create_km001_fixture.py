"""Author synthetic values against audited official field names. Never market evidence."""

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    columns = json.loads((root / "src/kmast/brokers/kis/ws_columns.json").read_text())
    rest = []
    daily = [
        {
            "stck_bsop_date": day,
            "stck_oprc": "100",
            "stck_hgpr": "110",
            "stck_lwpr": "95",
            "stck_clpr": "105",
            "acml_vol": "0" if day.endswith("14") else "1000",
        }
        for day in ("20261014", "20261015")
    ]
    cases = [
        (
            {"operation": "daily", "symbol": "005930", "start": "2026-10-14", "end": "2026-10-15"},
            {"output1": {}, "output2": daily},
        ),
        (
            {"operation": "minute_today", "symbol": "005930", "at": "09:05:00"},
            {
                "output1": {},
                "output2": [
                    {
                        "stck_bsop_date": "20261016",
                        "stck_cntg_hour": "090500",
                        "stck_oprc": "100",
                        "stck_hgpr": "110",
                        "stck_lwpr": "95",
                        "stck_prpr": "105",
                        "cntg_vol": "10",
                    }
                ],
            },
        ),
        (
            {"operation": "price", "symbol": "005930"},
            {"output": {"stck_prpr": "105", "acml_vol": "1000"}},
        ),
        (
            {"operation": "quote", "symbol": "005930"},
            {"output1": {"bidp1": "104", "askp1": "106", "bidp_rsqn1": "30", "askp_rsqn1": "40"}},
        ),
        ({"operation": "index", "symbol": "0001"}, {"output": {"bstp_nmix_prpr": "1000.12"}}),
    ]
    for request, response in cases:
        rest.append({"request": request, "response": {"rt_cd": "0", **response}})
    streams = []
    for tr_id, names in columns.items():
        row = {name: "0" for name in names}
        row.update(
            MKSC_SHRN_ISCD="005930",
            BSOP_HOUR="090459",
            BSOP_DATE="20261016",
            STCK_CNTG_HOUR="090459",
            STCK_PRPR="105",
            CNTG_VOL="10",
            ASKP1="106",
            BIDP1="104",
            ASKP_RSQN1="40",
            BIDP_RSQN1="30",
        )
        streams.append("0|" + tr_id + "|001|" + "^".join(row[name] for name in names))
    dart = [
        {
            "corp_code": "00126380",
            "stock_code": "005930",
            "rcept_no": "20261014000001",
            "rcept_dt": "20261014",
            "report_nm": "SYNTHETIC REPORT",
            "pblntf_ty": "A",
        },
        {
            "corp_code": "00126380",
            "stock_code": "005930",
            "rcept_no": "20261015000001",
            "rcept_dt": "20261015",
            "report_nm": "[기재정정] SYNTHETIC REPORT",
            "pblntf_ty": "A",
            "supersedes_receipt": "20261014000001",
        },
    ]
    output = root / "src/kmast/data/fixtures/market.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "origin": "SELF_AUTHORED_SYNTHETIC_NOT_REAL_MARKET_DATA",
                "official_commit": "2077773a69a428daf63e148182511f068cc45de3",
                "rest": rest,
                "stream": streams,
                "dart": dart,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
