"""Generate deployment secrets or make a consistent offline-readable SQLite backup."""

import argparse
import sqlite3
from pathlib import Path
from typing import cast

from cryptography.fernet import Fernet
from xkcdpass import xkcd_password as xp  # type: ignore[import-untyped]

from jobscout.config import get_settings
from jobscout.database import sqlite_path


def generate_registration_code() -> str:
    words = xp.generate_wordlist(
        wordfile="eff-short", min_length=2, max_length=5, valid_chars="[a-z]"
    )
    return cast(str, xp.generate_xkcdpassword(words, numwords=6, delimiter="-"))


def backup_database(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError("Choose a new backup file outside the source database.")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as backup:
            original.backup(backup)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate-secrets")
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "generate-secrets":
        print("REGISTRATION_CODE=" + generate_registration_code())
        print("CREDENTIALS_KEY=" + Fernet.generate_key().decode())
    else:
        backup_database(Path(sqlite_path(get_settings().database_url)), arguments.destination)


if __name__ == "__main__":
    main()
