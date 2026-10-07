import math
import sys

import pytest
from cryptography.fernet import Fernet
from xkcdpass import xkcd_password as xp  # type: ignore[import-untyped]

from jobscout.config import Settings
from jobscout.manage import main


def test_generated_registration_code_is_memorable_and_valid_for_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    words: list[str] = xp.generate_wordlist(
        wordfile="eff-short", min_length=2, max_length=5, valid_chars="[a-z]"
    )
    assert len(words) == len(set(words))
    assert all(word.isascii() and word.isalpha() and word.islower() for word in words)
    assert 6 * math.log2(len(words)) >= 60

    monkeypatch.setattr(sys, "argv", ["jobscout.manage", "generate-secrets"])
    main()
    values = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    code_words = values["REGISTRATION_CODE"].split("-")
    assert len(code_words) == 6
    assert all(word in words and 2 <= len(word) <= 5 for word in code_words)

    settings = Settings.model_validate(
        {
            "production": True,
            "public_origin": "https://jobscout.example.com",
            "cookie_secure": True,
            "registration_code": values["REGISTRATION_CODE"],
            "credentials_key": values["CREDENTIALS_KEY"],
        }
    )
    assert settings.registration_code.get_secret_value() == values["REGISTRATION_CODE"]
    Fernet(values["CREDENTIALS_KEY"].encode())
