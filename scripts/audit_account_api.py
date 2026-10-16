"""Explicitly invoked public GitHub document audit; never imports a broker or credentials."""

import hashlib
import json
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

COMMIT = "2077773a69a428daf63e148182511f068cc45de3"
NAMES = ("inquire_balance", "inquire_daily_ccld", "inquire_psbl_rvsecncl", "inquire_psbl_order")


def main() -> None:
    records = []
    directory = Path(tempfile.mkdtemp(prefix="km002-public-account-spec-"))
    for path in [
        *(
            f"examples_llm/domestic_stock/{name}/{prefix}{name}.py"
            for name in NAMES
            for prefix in ("", "chk_")
        ),
        "examples_user/domestic_stock/domestic_stock_functions_ws.py",
    ]:
        url = f"https://raw.githubusercontent.com/koreainvestment/open-trading-api/{COMMIT}/{path}"
        raw = urllib.request.urlopen(url, timeout=30).read()
        (directory / Path(path).name).write_bytes(raw)
        records.append({"path": path, "url": url, "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "commit": COMMIT,
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "PUBLIC_DOCUMENTS_ONLY_NO_ACCOUNT_ACCESS",
        "files": records,
    }
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km002/official_account_sources.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(directory)
    print(f"PASS: {len(records)} pinned public documents; account access NOT_EXECUTED")


if __name__ == "__main__":
    main()
