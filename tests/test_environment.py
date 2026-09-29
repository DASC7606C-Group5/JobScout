"""Smoke checks for the installed package and its runtime dependency.

These checks validate the development environment, not JobScout business behavior.
"""

import subprocess
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


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


class SmokeState(TypedDict):
    text: str


def test_langgraph_compiles_and_runs() -> None:
    """The locked LangGraph version must run on the project's Python version."""

    def uppercase(state: SmokeState) -> SmokeState:
        return {"text": state["text"].upper()}

    builder = StateGraph(SmokeState)
    builder.add_node("uppercase", uppercase)
    builder.add_edge(START, "uppercase")
    builder.add_edge("uppercase", END)

    result = builder.compile().invoke({"text": "jobscout"})

    assert result["text"] == "JOBSCOUT"
