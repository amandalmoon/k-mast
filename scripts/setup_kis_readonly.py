"""Human-run terminal setup. Secrets are entered without echo, outside the repository."""

import csv
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    if not sys.stdin.isatty():
        raise ValueError("interactive terminal required for hidden secret input")
    directory = Path.home() / ".kmast-readonly"
    path = directory / "credentials.json"
    if path.exists():
        raise ValueError("configuration already exists; refusing overwrite")
    environment = input("KIS key environment (LIVE or PAPER): ").strip().upper()
    if environment not in {"LIVE", "PAPER"}:
        raise ValueError("invalid environment")
    key = getpass.getpass("App key (hidden): ").strip()
    secret = getpass.getpass("App secret (hidden): ").strip()
    if not key or not secret:
        raise ValueError("credential pair required")
    directory.mkdir(mode=0o700, exist_ok=True)
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
        )
        sid = next(csv.reader(identity.stdout.decode().splitlines()))[1]
        subprocess.run(
            ["icacls", str(directory), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
        )
    config = {
        "environment": environment,
        "credential_environment": environment,
        "account_environment": environment,
        "account_ref": "READONLY_MARKET_ALIAS",
        "endpoint": "https://openapi.koreainvestment.com:9443"
        if environment == "LIVE"
        else "https://openapivts.koreainvestment.com:29443",
        "app_key": key,
        "app_secret": secret,
    }
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle)
    path.chmod(0o600)
    print("Saved local read-only configuration. No authentication was attempted.")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt):
        raise SystemExit("Setup stopped; no secret values are displayed.") from None
