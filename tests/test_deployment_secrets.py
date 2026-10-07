import sys

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from jobscout.config import Settings
from jobscout.manage import main


def test_generated_credentials_key_is_valid_for_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["jobscout.manage", "generate-secrets"])
    main()
    values = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert values.keys() == {"CREDENTIALS_KEY"}
    settings = Settings.model_validate(
        {
            "production": True,
            "public_origin": "https://jobscout.example.com",
            "cookie_secure": True,
            "credentials_key": values["CREDENTIALS_KEY"],
        }
    )
    cipher = Fernet(settings.credentials_key.get_secret_value().encode())
    assert cipher.decrypt(cipher.encrypt(b"synthetic-api-key")) == b"synthetic-api-key"


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_origin": "http://jobscout.example.com"},
        {"cookie_secure": False},
        {"credentials_key": ""},
        {"credentials_key": "invalid-key"},
    ],
)
def test_production_rejects_insecure_configuration(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as invalid:
        Settings.model_validate(
            {
                "production": True,
                "public_origin": "https://jobscout.example.com",
                "cookie_secure": True,
                "credentials_key": Fernet.generate_key().decode(),
                "llm_semantic_api_key": "synthetic-startup-secret",
                **overrides,
            }
        )
    assert "synthetic-startup-secret" not in str(invalid.value)
