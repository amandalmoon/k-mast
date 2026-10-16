"""Explicit public-document fetch only; never connects to a brokerage account."""

import hashlib
import json
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = "https://api.github.com/repos/koreainvestment/open-trading-api"
NAMES = (
    "inquire_daily_itemchartprice",
    "inquire_time_itemchartprice",
    "inquire_time_dailychartprice",
    "inquire_price",
    "inquire_asking_price_exp_ccn",
    "inquire_index_price",
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km001"
    output.mkdir(parents=True, exist_ok=True)
    commit = json.load(urllib.request.urlopen(REPO + "/commits/main", timeout=30))["sha"]
    paths = [f"examples_llm/domestic_stock/{name}/{name}.py" for name in NAMES]
    paths += [
        f"examples_llm/domestic_stock/{name}/chk_{name}.py"
        for name in (
            "inquire_daily_itemchartprice",
            "inquire_time_itemchartprice",
            "inquire_index_price",
            "inquire_asking_price_exp_ccn",
        )
    ]
    paths += [
        "examples_user/domestic_stock/domestic_stock_functions_ws.py",
        "examples_llm/kis_auth.py",
        "kis_devlp.yaml",
        "examples_llm/auth/auth_token/auth_token.py",
        "examples_llm/auth/auth_ws_token/auth_ws_token.py",
    ]
    local = Path(tempfile.mkdtemp(prefix="kmast-official-"))
    records = []
    for path in paths:
        url = f"https://raw.githubusercontent.com/koreainvestment/open-trading-api/{commit}/{path}"
        raw = urllib.request.urlopen(url, timeout=30).read()
        (local / Path(path).name).write_bytes(raw)
        records.append({"path": path, "url": url, "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "repository": REPO,
        "commit": commit,
        "checked_at": datetime.now(UTC).isoformat(),
        "files": records,
    }
    (output / "official_sources.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(local)
    print(commit)


if __name__ == "__main__":
    main()
