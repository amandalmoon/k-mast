from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, SecretStr, model_validator

from kmast.core.base import Contract, Identifier
from kmast.core.enums import Environment, Mode

ENDPOINTS = {
    Environment.PAPER: "https://openapivts.koreainvestment.com:29443",
    Environment.LIVE: "https://openapi.koreainvestment.com:9443",
}


class BrokerConfig(Contract):
    environment: Environment
    credential_environment: Environment
    account_environment: Environment
    account_ref: SecretStr = Field(repr=False, exclude=True)
    app_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    app_secret: SecretStr | None = Field(default=None, repr=False, exclude=True)
    endpoint: Identifier

    @model_validator(mode="after")
    def isolated(self) -> Self:
        if not (self.environment == self.credential_environment == self.account_environment):
            raise ValueError("environment mismatch")
        if self.endpoint != ENDPOINTS[self.environment]:
            raise ValueError("endpoint mismatch")
        if bool(self.app_key) != bool(self.app_secret):
            raise ValueError("credential pair incomplete")
        return self


class RuntimeConfig(Contract):
    mode: Mode = Mode.RESEARCH
    order_enabled: Literal[False] = False
    live_enabled: Literal[False] = False
    config_version: Identifier = "km000-v12"
    broker: BrokerConfig | None = None

    @model_validator(mode="after")
    def safe_mode(self) -> Self:
        if self.mode == Mode.LIVE:
            raise ValueError("LIVE is unavailable in KM-000")
        if self.mode == Mode.PAPER and self.broker and self.broker.environment != Environment.PAPER:
            raise ValueError("PAPER requires isolated paper broker")
        return self


def load_config(path: Path) -> RuntimeConfig:
    try:
        return RuntimeConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except Exception:
        # Never propagate parser/validation messages containing arbitrary secret inputs.
        raise ValueError("invalid configuration; execution blocked") from None


def require_order_permission() -> None:
    raise PermissionError("all broker orders are blocked in KM-000")
