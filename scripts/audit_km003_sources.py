"""Public document availability/hash audit. No market-data or authenticated requests."""

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SOURCES = (
    (
        "FSC_DAILY",
        "https://www.data.go.kr/data/15094808/openapi.do",
        "License/publication delay require review; Type 4 and redistribution restrictions stated",
    ),
    (
        "KRX",
        "https://openapi.krx.co.kr/contents/OPP/MAIN/main/index.cmd",
        "API key application and applicable market data use agreement required",
    ),
    (
        "DART",
        "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001",
        "Authentication key required; receipt date is not an intraday publication timestamp",
    ),
    (
        "KIS_DAILY",
        "https://raw.githubusercontent.com/koreainvestment/open-trading-api/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py",
        "Read-only auth authorized; key setup declined; authentication not attempted",
    ),
)


def main():
    records = []
    for name, url, note in SOURCES:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                raw = response.read(4 * 1024 * 1024)
                records.append(
                    {
                        "source": name,
                        "url": url,
                        "status": response.status,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "note": note,
                    }
                )
        except Exception:
            records.append(
                {
                    "source": name,
                    "url": url,
                    "status": "FETCH_UNAVAILABLE",
                    "sha256": None,
                    "note": note,
                }
            )
    manifest = {
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "PUBLIC_DOCUMENTS_ONLY",
        "sources": records,
        "actual_authentication_calls": 0,
        "real_market_rows": 0,
        "credential_setup": "USER_DECLINED_THIS_RUN",
        "A": "DATA_BLOCKED",
        "B": "DATA_BLOCKED",
        "C": "DATA_BLOCKED",
        "D": "DATA_BLOCKED",
    }
    path = Path(__file__).resolve().parents[1] / "artifacts/km003/data-source-audit.json"
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    print(
        "Public documents recorded; real data remains BLOCKED; no KIS/DART authentication attempted"
    )


if __name__ == "__main__":
    main()
