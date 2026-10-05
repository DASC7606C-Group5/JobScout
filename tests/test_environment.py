"""Check that the installed package imports outside the repository."""

import subprocess
import sys
from pathlib import Path


def test_package_imports_outside_repository(tmp_path: Path) -> None:
    """Imports must work through installation, without the repo on sys.path."""
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import jobscout.main; import jobscout.graph.builder; "
            "import jobscout.schemas.profile; import jobscout.services.profile_service",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
