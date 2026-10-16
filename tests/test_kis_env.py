import pytest

from scripts.read_kis_env import load_env


def template(**changes):
    values = dict(
        KIS_ENVIRONMENT="PAPER",
        KIS_APP_KEY="SYNTHETIC_KEY_ONLY",
        KIS_APP_SECRET="SYNTHETIC_SECRET_ONLY",
        KMAST_MODE="RESEARCH",
        KMAST_ORDER_ENABLED="false",
        KMAST_LIVE_ENABLED="false",
    )
    values.update(changes)
    return "\n".join(f"{key}={value}" for key, value in values.items())


def test_local_env_keeps_quoted_secrets_out_of_repr_and_serialization(tmp_path):
    path = tmp_path / ".env"
    path.write_text(template(KIS_APP_KEY='"SYNTHETIC_KEY_ONLY"'), encoding="utf-8")
    config = load_env(path)
    assert config.app_key.get_secret_value() == "SYNTHETIC_KEY_ONLY"
    assert "SYNTHETIC_KEY_ONLY" not in repr(config) + config.model_dump_json()
    assert "SYNTHETIC_SECRET_ONLY" not in repr(config) + config.model_dump_json()


@pytest.mark.parametrize(
    "override",
    [
        {"KMAST_ORDER_ENABLED": "true"},
        {"KMAST_LIVE_ENABLED": "true"},
        {"KIS_ENVIRONMENT": "WRONG"},
        {"KIS_APP_SECRET": ""},
    ],
)
def test_env_invalid_or_trading_flags_fail_closed_without_raw_inputs(tmp_path, override):
    path = tmp_path / ".env"
    path.write_text(template(**override), encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_env(path)
    assert str(error.value) == "local credential configuration invalid; inputs suppressed"
    assert "SYNTHETIC" not in str(error.value)


def test_duplicate_env_fields_are_rejected(tmp_path):
    path = tmp_path / ".env"
    path.write_text(template() + "\nKIS_APP_KEY=SYNTHETIC_CONFLICT", encoding="utf-8")
    with pytest.raises(ValueError, match="inputs suppressed"):
        load_env(path)
