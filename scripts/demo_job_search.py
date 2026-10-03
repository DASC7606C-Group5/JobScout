"""Offline/live Group 4 demo. Run through the installed project environment."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue, TypeAdapter, ValidationError

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.mock_web import FixtureWebClient
from jobscout.services.job_retrieval.models import SearchResult, workflow_error
from jobscout.services.job_retrieval.transport import FixtureClient
from jobscout.services.job_search_service import JobSearchService

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--input", type=Path, default=ROOT / "data/group4/unrestricted.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--candidate-limit", type=int, default=60)
    parser.add_argument("--result-limit", type=int, default=30)
    parser.add_argument("--detail-limit", type=int, default=5)
    args = parser.parse_args()
    started = time.perf_counter()
    requests: list[SearchRequest] = []
    try:
        requests = TypeAdapter(list[SearchRequest]).validate_json(
            args.input.read_text(encoding="utf-8-sig")
        )
        if args.mode == "mock":
            fixtures = TypeAdapter(dict[str, dict[str, JsonValue]]).validate_json(
                (ROOT / "data/group4/mock_sources.json").read_text(encoding="utf-8")
            )
            service = JobSearchService(
                client=FixtureClient(fixtures),
                web_client=FixtureWebClient(ROOT / "data/group4/mock_local_sources.json"),
                max_pages=args.max_pages,
                page_size=args.page_size,
                candidate_limit=args.candidate_limit,
                result_limit=args.result_limit,
                detail_limit=args.detail_limit,
            )
        else:
            service = JobSearchService(
                max_pages=args.max_pages,
                page_size=args.page_size,
                candidate_limit=args.candidate_limit,
                result_limit=args.result_limit,
                detail_limit=args.detail_limit,
            )
        result = service.search_many(requests)
    except OSError, ValidationError, ValueError:
        # ValidationError can echo user input: do not print it or a traceback.
        result = SearchResult(
            errors=[
                workflow_error(
                    "SEARCH_INPUT",
                    "Cannot read/validate input JSON or demo fixtures; expected a SearchRequest array.",
                )
            ]
        )
    output = {
        "mode": args.mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "requests": [r.model_dump(mode="json") for r in requests],
        "returned_count": len(result.raw_jobs),
        **result.model_dump(mode="json"),
    }
    content = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content + "\n", encoding="utf-8")
        except OSError:
            print("Cannot write output file.", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "output": str(args.output),
                    "returned_count": len(result.raw_jobs),
                    "errors": len(result.errors),
                    "warnings": len(result.warnings),
                    "outcomes": [o.model_dump() for o in result.outcomes],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(content)
    return (
        2
        if any(e.code in {"SEARCH_INPUT", "SEARCH_UNKNOWN_SOURCE"} for e in result.errors)
        else 1
        if result.errors
        else 0
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
